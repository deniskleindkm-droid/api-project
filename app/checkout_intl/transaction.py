"""
CheckoutTransaction lifecycle: quote -> select -> lock -> (paid) and re-quote.

The Delivery step calls `create_quoted()`. The Payment step calls
`lock_for_payment()`, which is the ONLY place a shipping method can become
the one that gets fulfilled, and it refuses to proceed on a stale or vanished
rate instead of quietly swapping in another one:

  - quote still fresh + chosen method present            -> lock as chosen
  - quote expired -> re-quote:
        same method, same supplier price                 -> refresh + lock
        method gone or price changed                     -> RequoteRequired
  - re-quote returns nothing                             -> RequoteRequired(options=[])
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from sqlmodel import Session

from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, flags, rates
from app.models.checkout_transaction import CheckoutTransaction

RateFetcher = Callable[[str, str, str, List[dict]], list]   # (country_id, postcode, city, products) -> raw methods


class RequoteRequired(Exception):
    def __init__(self, reason: str, options: List[dict]):
        super().__init__(reason)
        self.reason = reason
        self.options = options


class NoShippingAvailable(Exception):
    pass


def default_rate_fetcher(country_id: str, postcode: str, city: str, products: List[dict]) -> list:
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    return SilverbeneAdapter().get_shipping_methods(
        country_code=country_id, postcode=postcode, city=city,
        products=products, allow_fallback=False,
    )


def _supplier_products(items: List[dict]) -> List[dict]:
    return [{"option_id": i["supplier_option_id"], "qty": i["quantity"]} for i in items]


def fetch_options(address: addr_mod.StructuredAddress, items: List[dict],
                  fetcher: Optional[RateFetcher] = None) -> List[dict]:
    """Live Silverbene rates for the actual cart + destination -> policy-filtered internal options."""
    fetcher = fetcher or default_rate_fetcher
    parsed = addr_mod.to_parsed_address(address)
    raw = fetcher(parsed["country_code"], parsed["postal_code"], parsed["city"], _supplier_products(items))
    return rates.present(rates.normalize(raw))


def create_quoted(session: Session, *, address: addr_mod.StructuredAddress, items: List[dict],
                  is_guest: bool, fetcher: Optional[RateFetcher] = None) -> CheckoutTransaction:
    options = fetch_options(address, items, fetcher)
    if not options:
        raise NoShippingAvailable()
    now = datetime.utcnow()
    market = countries.get_market(address.country_code)
    tx = CheckoutTransaction(
        id=uuid.uuid4().hex,
        status="quoted",
        user_email=address.email.strip().lower(),
        is_guest=is_guest,
        first_name=address.first_name.strip(),
        last_name=address.last_name.strip(),
        country_code=address.country_code.upper(),
        supplier_country_id=market.silverbene_country_id,
        address_json=address.model_dump_json(),
        supplier_address_json=json.dumps(addr_mod.to_parsed_address(address)),
        items_json=json.dumps(items),
        quote_json=json.dumps({"options": options}),
        quote_fetched_at=now,
        quote_expires_at=now + timedelta(minutes=flags.quote_ttl_minutes()),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def load_options(tx: CheckoutTransaction) -> List[dict]:
    return json.loads(tx.quote_json or "{}").get("options", [])


def load_address(tx: CheckoutTransaction) -> addr_mod.StructuredAddress:
    return addr_mod.StructuredAddress(**json.loads(tx.address_json))


def load_items(tx: CheckoutTransaction) -> List[dict]:
    return json.loads(tx.items_json or "[]")


def _same_price(a: Optional[float], b: Optional[float]) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 0.005)


def lock_for_payment(session: Session, tx: CheckoutTransaction, method_id: str,
                     fetcher: Optional[RateFetcher] = None,
                     now: Optional[datetime] = None) -> CheckoutTransaction:
    if tx.status not in ("quoted", "locked"):
        raise ValueError(f"checkout is {tx.status}; cannot lock")
    now = now or datetime.utcnow()
    options = load_options(tx)
    chosen = next((o for o in options if o["method_id"] == method_id), None)
    if chosen is None:
        raise RequoteRequired("That delivery option is no longer available", [])

    if tx.quote_expires_at is None or now >= tx.quote_expires_at:
        fresh = fetch_options(load_address(tx), load_items(tx), fetcher)
        fresh_match = next((o for o in fresh if o["method_id"] == method_id), None)
        if fresh_match is None or not _same_price(fresh_match["supplier_price"], chosen["supplier_price"]):
            # Persist the new rates so the customer re-chooses against real ones.
            tx.quote_json = json.dumps({"options": fresh})
            tx.quote_fetched_at = now
            tx.quote_expires_at = now + timedelta(minutes=flags.quote_ttl_minutes())
            tx.updated_at = now
            session.add(tx)
            session.commit()
            raise RequoteRequired(
                "Delivery options changed while you were checking out" if fresh
                else "Delivery is currently unavailable to that address", fresh)
        chosen = fresh_match
        tx.quote_json = json.dumps({"options": fresh})
        tx.quote_fetched_at = now
        tx.quote_expires_at = now + timedelta(minutes=flags.quote_ttl_minutes())

    tx.shipping_method_id = chosen["method_id"]
    tx.shipping_method_name = chosen["name"]
    tx.shipping_eta = (chosen.get("eta") or {}).get("text")
    tx.shipping_supplier_price = chosen["supplier_price"]
    tx.status = "locked"
    tx.updated_at = now
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx
