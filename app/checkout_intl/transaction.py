"""
CheckoutTransaction lifecycle: pending -> quoted -> locked -> paid, with async (re-)quoting.

WHY ASYNC: Silverbene's rate endpoint measured 40-90 s per call (Stage 1B probe), far
beyond any acceptable request time. The Delivery step therefore returns immediately
with a `quoting` transaction; the rate fetch runs in the background and the browser
polls GET /checkout/{id}/options. A stale quote is likewise refreshed in the
background, never inline in the Pay request.

Customers choose a TIER (STANDARD / EXPRESS); the supplier method id behind it stays
server-side and is what gets locked and fulfilled.

Rules that keep the customer's choice honest:
  - lock only ever uses a method that was OFFERED for the chosen tier;
  - an expired quote is refreshed (background) before anything is locked;
  - if what the customer last SAW (ack) differs from the current offer -- different
    supplier method or different supplier price for that tier -- lock refuses with
    RequoteRequired instead of silently swapping;
  - nothing is fulfilled with a method the customer did not choose.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from sqlmodel import Session

import app.database as _db
from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, flags, rates
from app.models.checkout_transaction import CheckoutTransaction

RATE_TIMEOUT_SECONDS = 150

RateFetcher = Callable[[str, str, str, List[dict]], list]   # (country_id, postcode, city, products) -> raw methods


class RequoteRequired(Exception):
    def __init__(self, reason: str, options: List[dict], pending: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.options = options
        self.pending = pending            # True: a background re-quote was started; poll /options


class NoShippingAvailable(Exception):
    pass


def default_rate_fetcher(country_id: str, postcode: str, city: str, products: List[dict]) -> list:
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    return SilverbeneAdapter().get_shipping_methods(
        country_code=country_id, postcode=postcode, city=city,
        products=products, allow_fallback=False,
        timeout=RATE_TIMEOUT_SECONDS, attempts=1,      # measured 6-110 s per call; do not cut it off at 30 s
    )


def _supplier_products(items: List[dict]) -> List[dict]:
    return [{"option_id": i["supplier_option_id"], "qty": i["quantity"]} for i in items]


def fetch_quote(address: addr_mod.StructuredAddress, items: List[dict],
                fetcher: Optional[RateFetcher] = None) -> dict:
    """Live Silverbene rates for the actual cart + destination.
    Returns {"options": every normalized method with its tier, "offered": ids a customer may pick}."""
    fetcher = fetcher or default_rate_fetcher
    parsed = addr_mod.to_parsed_address(address)
    raw = fetcher(parsed["country_code"], parsed["postal_code"], parsed["city"], _supplier_products(items))
    options = rates.normalize(raw, parsed["country_code"])
    offered = rates.present(options)
    return {"options": options, "offered": [o["method_id"] for o in offered],
            "fallback": any(o.get("fallback") for o in offered)}


# ── creation / background quoting ─────────────────────────────────────────────

def create_pending(session: Session, *, address: addr_mod.StructuredAddress, items: List[dict],
                   is_guest: bool) -> CheckoutTransaction:
    market = countries.get_market(address.country_code)
    tx = CheckoutTransaction(
        id=uuid.uuid4().hex,
        status="quoting",
        user_email=address.email.strip().lower(),
        is_guest=is_guest,
        first_name=address.first_name.strip(),
        last_name=address.last_name.strip(),
        country_code=address.country_code.upper(),
        supplier_country_id=market.silverbene_country_id,
        address_json=address.model_dump_json(),
        supplier_address_json=json.dumps(addr_mod.to_parsed_address(address)),
        items_json=json.dumps(items),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def run_quote(checkout_id: str, fetcher: Optional[RateFetcher] = None) -> None:
    """Background job: fetch rates and move the transaction quoting -> quoted | unavailable. Never raises."""
    try:
        with Session(_db.engine) as session:
            tx = session.get(CheckoutTransaction, checkout_id)
            if tx is None or tx.status != "quoting":
                return
            try:
                quote = fetch_quote(load_address(tx), load_items(tx), fetcher)
                error = None
            except Exception as e:                       # supplier down / timeout: fail closed, retryable
                quote, error = {"options": [], "offered": [], "fallback": False}, f"{type(e).__name__}: {e}"
            now = datetime.utcnow()
            tx.quote_json = json.dumps(quote)
            tx.quote_fetched_at = now
            tx.quote_expires_at = now + timedelta(minutes=flags.quote_ttl_minutes())
            tx.quote_error = error
            tx.status = "quoted" if quote["offered"] else "unavailable"
            tx.updated_at = now
            session.add(tx)
            session.commit()
    except Exception as e:                               # noqa: BLE001 - background jobs must not crash the worker
        print(f"[IntlCheckout] run_quote({checkout_id}) failed: {e}")


def begin_requote(session: Session, tx: CheckoutTransaction) -> CheckoutTransaction:
    tx.status = "quoting"
    tx.quote_error = None
    tx.updated_at = datetime.utcnow()
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


# ── reading ───────────────────────────────────────────────────────────────────

def load_options(tx: CheckoutTransaction) -> List[dict]:
    """Every quoted method (both tiers), regardless of what is currently offered."""
    return json.loads(tx.quote_json or "{}").get("options", [])


def offered_options(tx: CheckoutTransaction) -> List[dict]:
    doc = json.loads(tx.quote_json or "{}")
    by_id = {o["method_id"]: o for o in doc.get("options", [])}
    return [by_id[i] for i in doc.get("offered", []) if i in by_id]


def load_address(tx: CheckoutTransaction) -> addr_mod.StructuredAddress:
    return addr_mod.StructuredAddress(**json.loads(tx.address_json))


def load_items(tx: CheckoutTransaction) -> List[dict]:
    return json.loads(tx.items_json or "[]")


def _snapshot(options: List[dict]) -> dict:
    return {o["tier"]: {"method_id": o["method_id"], "price": o["supplier_price"]} for o in options}


def _same_price(a: Optional[float], b: Optional[float]) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 0.005)


def view_options(session: Session, tx: CheckoutTransaction) -> dict:
    """
    Polling read. Marks the currently offered options as SEEN by the customer (ack) and
    reports whether they differ from what the customer had seen before, so the UI can
    require a fresh choice instead of continuing on stale assumptions.
    """
    if tx.status == "quoting":
        return {"status": "pending", "options": [], "changed": False}
    if tx.status == "unavailable":
        return {"status": "unavailable", "options": [], "changed": False}
    offered = offered_options(tx)
    prev = json.loads(tx.ack_json) if tx.ack_json else None
    now_snap = _snapshot(offered)
    changed = prev is not None and prev != now_snap
    if prev != now_snap:
        tx.ack_json = json.dumps(now_snap)
        session.add(tx)
        session.commit()
    return {"status": "ready", "options": offered, "changed": changed}


# ── locking ───────────────────────────────────────────────────────────────────

def lock_for_payment(session: Session, tx: CheckoutTransaction, tier: str,
                     now: Optional[datetime] = None) -> CheckoutTransaction:
    if tx.status == "quoting":
        raise RequoteRequired("Still finding delivery options", [], pending=True)
    if tx.status not in ("quoted", "locked"):
        raise ValueError(f"checkout is {tx.status}; cannot lock")
    now = now or datetime.utcnow()

    if tx.quote_expires_at is None or now >= tx.quote_expires_at:
        begin_requote(session, tx)         # refresh in the background; caller schedules run_quote
        raise RequoteRequired("Refreshing your delivery options", [], pending=True)

    offered = offered_options(tx)
    chosen = next((o for o in offered if o["tier"] == tier), None)
    if chosen is None:
        raise RequoteRequired("That delivery option is no longer available", offered)

    ack = json.loads(tx.ack_json) if tx.ack_json else None
    seen = (ack or {}).get(tier)
    if seen is not None and (seen["method_id"] != chosen["method_id"]
                             or not _same_price(seen["price"], chosen["supplier_price"])):
        tx.ack_json = json.dumps(_snapshot(offered))         # they are about to be shown the new offer
        session.add(tx)
        session.commit()
        raise RequoteRequired("Delivery options changed while you were checking out", offered)

    tx.shipping_method_id = chosen["method_id"]
    tx.shipping_method_name = chosen["name"]
    tx.shipping_eta = (chosen.get("eta") or {}).get("text")
    tx.shipping_supplier_price = chosen["supplier_price"]
    tx.shipping_tier = chosen["tier"]
    tx.status = "locked"
    tx.updated_at = now
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx
