"""
Fulfillment context for orders that came through the international checkout.

Both process_order_background (payments.py) and order_recovery_agent load
this instead of re-parsing a comma string or re-choosing a carrier. It
returns everything place_order needs, with the EXACT shipping method the
customer chose before paying. Orders without a checkout_id return None and
follow the untouched legacy path.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from app.checkout_intl import address as addr_mod
from app.checkout_intl import transaction as txn
from app.database import engine
from app.models.checkout_transaction import CheckoutTransaction


def load_context(checkout_id: Optional[str]) -> Optional[dict]:
    if not checkout_id:
        return None
    with Session(engine) as session:
        tx = session.get(CheckoutTransaction, checkout_id)
        if tx is None or not tx.shipping_method_id:
            return None
        a = txn.load_address(tx)
        return {
            "checkout_id": tx.id,
            "customer": addr_mod.to_supplier_customer(a),
            "address": addr_mod.to_parsed_address(a),
            "customer_first": a.first_name.strip().capitalize() or "Customer",
            "customer_last": a.last_name.strip().capitalize() or "Customer",
            "shipping_method": tx.shipping_method_id,
            "shipping_price": tx.shipping_supplier_price,
            "shipping_title": tx.shipping_method_name,
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
