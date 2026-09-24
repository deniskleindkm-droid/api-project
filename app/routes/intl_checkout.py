"""
International two-step checkout (Stage 1). Inert unless the INTL_CHECKOUT flag
is on -- see app/checkout_intl/flags.py. The legacy /payments/create-checkout
and /payments/guest-checkout endpoints are untouched and remain the default.

  GET  /checkout/config          flag state + country registry for the selector
  POST /checkout/delivery        Step A: validate address + cart, get Silverbene
                                 rates for the real cart/destination, lock a quote
  POST /checkout/{id}/pay        Step B: lock the chosen method (re-quoting if it
                                 went stale), create the payment session

Pricing is frozen: Stripe line items, currency and Meta success params are
byte-for-byte what the legacy endpoints send.
"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth_utils import verify_token
from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, flags, items as items_mod, rates
from app.checkout_intl import payment_providers
from app.checkout_intl import transaction as txn
from app.database import get_session
from app.models.cart import CartItem
from app.models.checkout_transaction import CheckoutTransaction
from app.models.product import Product

router = APIRouter()

GUEST_SUCCESS_URL = "https://mikisi.co/"
ACCOUNT_FRONTEND_URL = "https://deniskleindkm-droid.github.io/api-project"


def _require_enabled():
    if not flags.intl_checkout_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _bearer_email(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    payload = verify_token(header[7:].strip())
    return payload.get("sub") if payload else None


class GuestLine(BaseModel):
    product_id: int
    quantity: int = 1
    selected_size: Optional[str] = None
    selected_color: Optional[str] = None
    selected_option_id: Optional[str] = None
    variant_id: Optional[int] = None


class DeliveryRequest(BaseModel):
    address: addr_mod.StructuredAddress
    items: List[GuestLine] = []          # guests send their cart; signed-in users' cart is read server-side


class PayRequest(BaseModel):
    shipping_method_id: str
    payment_provider: str = "stripe"


@router.get("/checkout/config")
def checkout_config():
    if not flags.intl_checkout_enabled():
        return {"enabled": False}
    return {
        "enabled": True,
        "markets": [m.public_dict() for m in countries.checkout_markets()],
        "payment": {"providers": ["stripe"], "presentment_currency": "USD"},
    }


def _lines_for_user(session: Session, email: str) -> List[dict]:
    cart = session.exec(select(CartItem).where(CartItem.user_id == email)).all()
    return [{
        "product_id": c.product_id, "quantity": c.quantity,
        "selected_size": c.selected_size, "selected_color": c.selected_color,
        "selected_option_id": c.selected_option_id, "variant_id": c.variant_id,
    } for c in cart]


def _options_payload(tx: CheckoutTransaction, options: List[dict]) -> dict:
    return {"checkout_id": tx.id,
            "options": [rates.customer_view(o) for o in options],
            "expires_at": tx.quote_expires_at.isoformat() + "Z" if tx.quote_expires_at else None}


@router.post("/checkout/delivery")
def delivery_step(body: DeliveryRequest, request: Request, session: Session = Depends(get_session)):
    _require_enabled()
    error = addr_mod.validate(body.address)
    if error:
        raise HTTPException(status_code=400, detail=error)

    account_email = _bearer_email(request)
    lines = _lines_for_user(session, account_email) if account_email else [g.model_dump() for g in body.items]
    try:
        validated = items_mod.validate_cart(session, lines)
    except items_mod.ItemError as e:
        raise HTTPException(status_code=400, detail=e.message)

    try:
        tx = txn.create_quoted(session, address=body.address, items=validated, is_guest=not account_email)
    except txn.NoShippingAvailable:
        raise HTTPException(status_code=422, detail=(
            "We can't offer delivery to that address right now. "
            "Please check the postcode or try another address."))
    if account_email:
        tx.user_email = account_email
        session.add(tx)
        session.commit()
    return _options_payload(tx, txn.load_options(tx))


def _stripe_line_items(session: Session, tx: CheckoutTransaction):
    """Identical amounts/currency/naming to the legacy endpoints (pricing frozen)."""
    line_items, content_ids, guest_meta, value = [], [], [], 0.0
    for line in txn.load_items(tx):
        product = session.get(Product, line["product_id"])
        if not product:
            raise HTTPException(status_code=400, detail="An item in your cart is no longer available")
        name = (f"Mikisi — {product.name[:50]}" if tx.is_guest else f"{product.brand} - {product.name}")
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": name, "description": (product.description or "")[:50]},
                "unit_amount": int(product.final_price * 100),
            },
            "quantity": line["quantity"],
        })
        content_ids.append(str(product.id))
        value += product.final_price * line["quantity"]
        guest_meta.append({
            "product_id": product.id, "quantity": line["quantity"],
            "selected_size": line.get("selected_size"), "selected_color": line.get("selected_color"),
            "selected_option_id": line.get("supplier_option_id"), "variant_id": line.get("variant_id"),
        })
    return line_items, content_ids, guest_meta, value


@router.post("/checkout/{checkout_id}/pay")
def pay_step(checkout_id: str, body: PayRequest, request: Request,
             session: Session = Depends(get_session)):
    _require_enabled()
    tx = session.get(CheckoutTransaction, checkout_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    if tx.status not in ("quoted", "locked"):
        raise HTTPException(status_code=409, detail="This checkout has already been completed")

    account_email = _bearer_email(request)
    if tx.is_guest == bool(account_email):
        raise HTTPException(status_code=403, detail="Checkout does not belong to this session")
    if account_email and tx.user_email != account_email:
        raise HTTPException(status_code=403, detail="Checkout does not belong to this account")

    # Signed-in orders are fulfilled from the live cart (legacy behavior), so it
    # must still match exactly what was quoted.
    if account_email:
        try:
            current = items_mod.validate_cart(session, _lines_for_user(session, account_email))
        except items_mod.ItemError as e:
            raise HTTPException(status_code=400, detail=e.message)
        key = lambda l: (l["product_id"], l["quantity"], l["supplier_option_id"])
        if sorted(map(key, current)) != sorted(map(key, txn.load_items(tx))):
            raise HTTPException(status_code=409, detail={"code": "cart_changed",
                                "message": "Your cart changed - please review delivery again"})

    try:
        tx = txn.lock_for_payment(session, tx, body.shipping_method_id)
    except txn.RequoteRequired as e:
        raise HTTPException(status_code=409, detail={
            "code": "requote", "message": e.reason,
            "options": [rates.customer_view(o) for o in e.options],
            "checkout_id": tx.id})

    try:
        provider = payment_providers.get_provider(body.payment_provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    line_items, content_ids, guest_meta, value = _stripe_line_items(session, tx)
    a = txn.load_address(tx)
    base = ACCOUNT_FRONTEND_URL if account_email else GUEST_SUCCESS_URL.rstrip("/")
    join = "?" if account_email else "/?"
    success_params = (f"payment=success&value={value:.2f}&currency=usd"
                      f"&content_ids={','.join(content_ids)}&session_id={{CHECKOUT_SESSION_ID}}")
    metadata = {
        "user_email": tx.user_email,
        "shipping_address": addr_mod.to_legacy_string(a),
        "shipping_method": "intl",
        "phone": a.phone.strip(),
        "checkout_id": tx.id,
    }
    if not account_email:
        metadata.update({"first_name": tx.first_name, "last_name": tx.last_name,
                         "guest_items": json.dumps(guest_meta), "is_guest": "true"})
    session_obj = provider.create_session(
        line_items=line_items,
        success_url=f"{base}{join}{success_params}",
        cancel_url=(f"{ACCOUNT_FRONTEND_URL}?payment=cancelled" if account_email else GUEST_SUCCESS_URL),
        customer_email=tx.user_email,
        metadata=metadata,
    )
    tx.payment_provider = body.payment_provider
    tx.payment_ref = getattr(session_obj, "id", None)
    session.add(tx)
    session.commit()
    return {"checkout_url": session_obj.url, "checkout_id": tx.id}
