"""
Fulfillment context for orders that came through the international checkout.

Both process_order_background (payments.py) and order_recovery_agent load
this instead of re-parsing a comma string or re-choosing a carrier. It
returns everything place_order needs, with the EXACT shipping method the
customer chose before paying. Orders without a checkout_id return None and
follow the untouched legacy path.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from sqlmodel import Session

from app.checkout_intl import address as addr_mod
from app.checkout_intl import rates
from app.checkout_intl import transaction as txn
from app.database import engine
from app.models.checkout_transaction import CheckoutTransaction


def _alert_fallback(tx, picked: dict) -> None:
    try:
        from app.agents.email_partner import send_email
        owner = os.getenv("DENNIS_EMAIL")
        if owner:
            send_email(to=owner, subject="Shipping fallback used on an international order",
                       body=(f"<p>Checkout {tx.id} ({tx.country_code}) chose {tx.shipping_method_id} but "
                             f"Silverbene offered {picked['name']} instead ({picked['reason']}).</p>"), is_html=True)
    except Exception as e:                                          # never block fulfillment on an alert
        print(f"[IntlFulfillment] fallback alert failed: {e}")


def load_context(checkout_id: Optional[str]) -> Optional[dict]:
    if not checkout_id:
        return None
    with Session(engine) as session:
        tx = session.get(CheckoutTransaction, checkout_id)
        if tx is None or not tx.shipping_method_id:
            return None
        if tx.shipping_resolved_json and tx.shipping_method_id in ("STANDARD", "EXPRESS"):
            # Already resolved once (a retry): keep the same real method instead of re-deciding.
            r = json.loads(tx.shipping_resolved_json)
            a0 = txn.load_address(tx)
            return {"checkout_id": tx.id, "resolution_failed": False, "resolution_note": None,
                    "customer": txn.addr_mod.to_supplier_customer(a0), "address": txn.addr_mod.to_parsed_address(a0),
                    "customer_first": a0.first_name.strip().capitalize() or "Customer",
                    "customer_last": a0.last_name.strip().capitalize() or "Customer",
                    "shipping_method": r["method_id"], "shipping_price": r["supplier_price"],
                    "shipping_title": r["name"]}
        a = txn.load_address(tx)
        chosen_method = tx.shipping_method_id
        chosen_price, chosen_title = tx.shipping_supplier_price, tx.shipping_method_name
        resolution_failed, resolution_note = False, None
        if tx.shipping_method_id in ("STANDARD", "EXPRESS"):
            # Class choice: pick the real carrier NOW from live rates for this exact cart + address.
            try:
                live = txn.default_rate_fetcher(
                    txn.addr_mod.to_parsed_address(a)["country_code"], a.postal_code, a.city,
                    txn._supplier_products(txn.load_items(tx)))
                picked = rates.resolve_class_method(tx.country_code, live, tx.shipping_method_id)
            except Exception as e:                                # noqa: BLE001 - supplier down/timeout: retry later
                picked, resolution_note = None, f"{type(e).__name__}: {e}"
            if picked is None:
                resolution_failed = True
                resolution_note = resolution_note or "no suitable supplier method available"
            else:
                chosen_method, chosen_price, chosen_title = picked["method_id"], picked["supplier_price"], picked["name"]
                if picked["fallback"]:
                    resolution_note = f"fallback used: {picked['reason']}"
                    _alert_fallback(tx, picked)
                tx.shipping_resolved_json = json.dumps({"class": tx.shipping_method_id, **picked})
                session.add(tx)
                session.commit()
        return {
            "resolution_failed": resolution_failed, "resolution_note": resolution_note,
            "checkout_id": tx.id,
            "customer": addr_mod.to_supplier_customer(a),
            "address": addr_mod.to_parsed_address(a),
            "customer_first": a.first_name.strip().capitalize() or "Customer",
            "customer_last": a.last_name.strip().capitalize() or "Customer",
            "shipping_method": chosen_method,
            "shipping_price": chosen_price,
            "shipping_title": chosen_title,
        }


def place_kwargs(ctx: dict) -> dict:
    """The extra place_order() kwargs that pin the customer's exact method."""
    return {
        "shipping_method": ctx["shipping_method"],
        "shipping_price": ctx["shipping_price"],
        "shipping_title": ctx["shipping_title"],
    }


def mark_paid(checkout_id: Optional[str], payment_ref: Optional[str]) -> None:
    if not checkout_id:
        return
    from datetime import datetime
    with Session(engine) as session:
        tx = session.get(CheckoutTransaction, checkout_id)
        if tx and tx.status in ("locked", "quoted"):
            tx.status = "paid"
            tx.payment_ref = payment_ref or tx.payment_ref
            tx.updated_at = datetime.utcnow()
            session.add(tx)
            session.commit()
