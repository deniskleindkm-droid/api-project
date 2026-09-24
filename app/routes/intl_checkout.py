"""
International two-step checkout (Stage 1 / 1B). Inert unless the INTL_CHECKOUT flag
is on -- see app/checkout_intl/flags.py. The legacy /payments/create-checkout
and /payments/guest-checkout endpoints are untouched and remain the default.

  GET  /checkout/config                 flag state + country registry for the selector
  POST /checkout/delivery               Step A: validate address + cart, get Silverbene
                                        rates for the real cart/destination, lock a quote
  POST /checkout/{id}/pay               Step B: lock the chosen method (re-quoting if it
                                        went stale), create the payment session
  GET  /checkout/paypal/return          PayPal approval return -> capture -> fulfill
  POST /checkout/paypal/webhook         PayPal webhook (signature-verified)

Pricing is frozen: Stripe/PayPal amounts and Meta success params are what the legacy
endpoints send (USD, product.final_price).
"""
import json
import os
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth_utils import verify_token
from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, flags, items as items_mod, rates
from app.checkout_intl import payment_providers, paypal
from app.checkout_intl import transaction as txn
from app.database import get_session
from app.models.cart import CartItem
from app.models.checkout_transaction import CheckoutTransaction
from app.models.product import Product

router = APIRouter()

GUEST_SUCCESS_URL = "https://mikisi.co/"
ACCOUNT_FRONTEND_URL = "https://deniskleindkm-droid.github.io/api-project"


def _api_base() -> str:
    return os.getenv("PUBLIC_API_BASE", "https://api-project-production-d424.up.railway.app").rstrip("/")


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
    shipping_tier: str                   # "STANDARD" | "EXPRESS" -- never a supplier method id
    payment_provider: str = "stripe"


@router.get("/checkout/config")
def checkout_config():
    if not flags.intl_checkout_enabled():
        return {"enabled": False}
    providers = ["stripe"] + (["paypal"] if paypal.paypal_enabled() else [])
    return {
        "enabled": True,
        "markets": [m.public_dict() for m in countries.checkout_markets()],
        "payment": {"providers": providers, "presentment_currency": "USD"},
    }


def _lines_for_user(session: Session, email: str) -> List[dict]:
    cart = session.exec(select(CartItem).where(CartItem.user_id == email)).all()
    return [{
        "product_id": c.product_id, "quantity": c.quantity,
        "selected_size": c.selected_size, "selected_color": c.selected_color,
        "selected_option_id": c.selected_option_id, "variant_id": c.variant_id,
    } for c in cart]


def _options_payload(session: Session, tx: CheckoutTransaction) -> dict:
    v = txn.view_options(session, tx)
    return {"checkout_id": tx.id, "status": v["status"], "changed": v["changed"],
            "options": [rates.customer_view(o) for o in v["options"]],
            "expires_at": tx.quote_expires_at.isoformat() + "Z" if tx.quote_expires_at else None}


@router.post("/checkout/delivery")
def delivery_step(body: DeliveryRequest, request: Request, background_tasks: BackgroundTasks,
                  session: Session = Depends(get_session)):
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

    # Silverbene's rate lookup takes tens of seconds, so it runs in the background;
    # the browser polls GET /checkout/{id}/options until status is ready|unavailable.
    tx = txn.create_pending(session, address=body.address, items=validated, is_guest=not account_email)
    if account_email:
        tx.user_email = account_email
        session.add(tx)
        session.commit()
    background_tasks.add_task(txn.run_quote, tx.id)
    return {"checkout_id": tx.id, "status": "pending"}


def _bg(tasks: BackgroundTasks, fn, *args):
    tasks.add_task(fn, *args)
    return tasks


def _owned_tx(session: Session, checkout_id: str, request: Request) -> CheckoutTransaction:
    tx = session.get(CheckoutTransaction, checkout_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    account_email = _bearer_email(request)
    if tx.is_guest == bool(account_email) or (account_email and tx.user_email != account_email):
        raise HTTPException(status_code=403, detail="Checkout does not belong to this session")
    return tx


@router.get("/checkout/{checkout_id}/options")
def delivery_options(checkout_id: str, request: Request, session: Session = Depends(get_session)):
    _require_enabled()
    tx = _owned_tx(session, checkout_id, request)
    payload = _options_payload(session, tx)
    if payload["status"] == "unavailable":
        payload["message"] = ("We can't offer delivery to that address right now. "
                              "Please check the postcode or try another address.")
    return payload


def _order_lines(session: Session, tx: CheckoutTransaction):
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


def _order_metadata(tx: CheckoutTransaction, guest_meta: list) -> dict:
    a = txn.load_address(tx)
    metadata = {
        "user_email": tx.user_email,
        "shipping_address": addr_mod.to_legacy_string(a),
        "shipping_method": "intl",
        "phone": a.phone.strip(),
        "checkout_id": tx.id,
    }
    if tx.is_guest:
        metadata.update({"first_name": tx.first_name, "last_name": tx.last_name,
                         "guest_items": json.dumps(guest_meta), "is_guest": "true"})
    return metadata


def _success_url(tx: CheckoutTransaction, value: float, content_ids: list, session_ref: str) -> str:
    base = GUEST_SUCCESS_URL.rstrip("/") + "/" if tx.is_guest else ACCOUNT_FRONTEND_URL
    return (f"{base}?payment=success&value={value:.2f}&currency=usd"
            f"&content_ids={','.join(content_ids)}&session_id={session_ref}")


def _cancel_url(tx: CheckoutTransaction) -> str:
    return GUEST_SUCCESS_URL if tx.is_guest else f"{ACCOUNT_FRONTEND_URL}?payment=cancelled"


@router.post("/checkout/{checkout_id}/pay")
def pay_step(checkout_id: str, body: PayRequest, request: Request, background_tasks: BackgroundTasks,
             session: Session = Depends(get_session)):
    _require_enabled()
    tx = session.get(CheckoutTransaction, checkout_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    if tx.status == "unavailable":
        raise HTTPException(status_code=409, detail={
            "code": "requote", "pending": False, "options": [], "checkout_id": tx.id,
            "message": "Delivery is currently unavailable to that address"})
    if tx.status not in ("quoted", "locked", "quoting"):
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
        provider = payment_providers.get_provider(body.payment_provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tx = txn.lock_for_payment(session, tx, body.shipping_tier.upper())
    except txn.RequoteRequired as e:
        body_409 = {"detail": {"code": "requote", "message": e.reason, "pending": e.pending,
                               "options": [rates.customer_view(o) for o in e.options],
                               "checkout_id": tx.id}}
        if e.pending and tx.quote_fetched_at is not None:
            # Stale quote: refresh in the background, then the browser polls /options.
            # (Returned as a response, not raised: FastAPI drops background tasks on an exception.)
            return JSONResponse(status_code=409, content=body_409,
                                background=_bg(background_tasks, txn.run_quote, tx.id))
        return JSONResponse(status_code=409, content=body_409)

    line_items, content_ids, guest_meta, value = _order_lines(session, tx)
    metadata = _order_metadata(tx, guest_meta)

    if body.payment_provider == "paypal":
        # PayPal redirects to OUR backend to capture, then we redirect on to the storefront.
        metadata["attempt"] = str(tx.payment_attempts)
        return_url = f"{_api_base()}/checkout/paypal/return?checkout_id={tx.id}"
        cancel_url = f"{_api_base()}/checkout/paypal/cancel?checkout_id={tx.id}"
        session_obj = provider.create_session(line_items=line_items, success_url=return_url,
                                              cancel_url=cancel_url, customer_email=tx.user_email,
                                              metadata=metadata)
    else:
        session_obj = provider.create_session(
            line_items=line_items,
            success_url=_success_url(tx, value, content_ids, "{CHECKOUT_SESSION_ID}"),
            cancel_url=_cancel_url(tx), customer_email=tx.user_email, metadata=metadata)

    tx.payment_provider = body.payment_provider
    tx.payment_ref = getattr(session_obj, "id", None)
    tx.payment_attempts = (tx.payment_attempts or 0) + 1
    session.add(tx)
    session.commit()
    return {"checkout_url": session_obj.url, "checkout_id": tx.id}


# ── PayPal capture / fulfillment ─────────────────────────────────────────────

def capture_and_fulfill(session: Session, tx: CheckoutTransaction, paypal_order_id: str,
                        background_tasks: BackgroundTasks, client: Optional[paypal.PayPalClient] = None) -> dict:
    """
    Idempotent: capture (PayPal replays the original result for a repeat), verify the
    captured amount equals what Mikisi computed server-side, then hand off to the same
    order pipeline Stripe uses, keyed "pp_<order id>" so a replayed webhook/return can
    never create a second supplier order.
    """
    from app.routes.payments import process_order_background
    client = client or paypal.PayPalClient()
    result = client.capture_order(paypal_order_id)
    if result.status != "COMPLETED":
        return {"status": result.status, "fulfilled": False}

    _, content_ids, guest_meta, value = _order_lines(session, tx)
    if result.amount is None or abs(result.amount - value) > 0.005 or (result.currency or "").upper() != "USD":
        tx.status = "needs_attention"
        session.add(tx)
        session.commit()
        _alert_owner(f"PayPal capture mismatch for checkout {tx.id}",
                     f"Captured {result.amount} {result.currency} but expected {value:.2f} USD "
                     f"(PayPal order {paypal_order_id}). Not fulfilled.")
        return {"status": "amount_mismatch", "fulfilled": False}

    tx.payment_capture_id = result.capture_id
    tx.payment_ref = f"pp_{paypal_order_id}"
    session.add(tx)
    session.commit()
    metadata = _order_metadata(tx, guest_meta)
    metadata["stripe_session_id"] = f"pp_{paypal_order_id}"       # shared idempotency key column
    background_tasks.add_task(process_order_background, {"metadata": metadata})
    return {"status": "COMPLETED", "fulfilled": True, "value": value, "content_ids": content_ids,
            "already_captured": result.already_captured}


def _alert_owner(subject: str, body: str):
    try:
        from app.agents.email_partner import send_email
        owner = os.getenv("DENNIS_EMAIL")
        if owner:
            send_email(to=owner, subject=f"⚠️ {subject}", body=f"<p>{body}</p>", is_html=True)
    except Exception as e:                       # never let alerting break payment handling
        print(f"[IntlCheckout] alert failed: {e}")


@router.get("/checkout/paypal/return")
def paypal_return(checkout_id: str, token: str, background_tasks: BackgroundTasks,
                  session: Session = Depends(get_session)):
    _require_enabled()
    if not paypal.paypal_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    tx = session.get(CheckoutTransaction, checkout_id)
    if tx is None or tx.payment_provider != "paypal":
        raise HTTPException(status_code=404, detail="Checkout not found")
    try:
        outcome = capture_and_fulfill(session, tx, token, background_tasks)
    except paypal.PayPalError as e:
        print(f"[IntlCheckout] PayPal capture failed for {checkout_id}: {e} {e.body}")
        return RedirectResponse(_cancel_url(tx) + ("&" if "?" in _cancel_url(tx) else "?") + "payment=failed", status_code=303)
    if outcome.get("fulfilled"):
        return RedirectResponse(_success_url(tx, outcome["value"], outcome["content_ids"], f"pp_{token}"),
                                status_code=303)
    return RedirectResponse(_cancel_url(tx), status_code=303)


@router.get("/checkout/paypal/cancel")
def paypal_cancel(checkout_id: str, session: Session = Depends(get_session)):
    _require_enabled()
    tx = session.get(CheckoutTransaction, checkout_id)
    # Nothing was captured; the checkout stays "locked" and can be paid again (new PayPal order).
    return RedirectResponse(_cancel_url(tx) if tx else GUEST_SUCCESS_URL, status_code=303)


@router.post("/checkout/paypal/webhook")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks,
                         session: Session = Depends(get_session)):
    if not (flags.intl_checkout_enabled() and paypal.paypal_enabled()):
        raise HTTPException(status_code=404, detail="Not found")
    event = await request.json()
    client = paypal.PayPalClient()
    if not client.verify_webhook(dict(request.headers), event):
        raise HTTPException(status_code=400, detail="Invalid signature")

    etype, resource = event.get("event_type", ""), event.get("resource", {}) or {}
    if etype == "CHECKOUT.ORDER.APPROVED":
        # Customer approved but never returned to our page -> capture now so a payment
        # never depends on the browser finishing the redirect.
        unit = (resource.get("purchase_units") or [{}])[0]
        tx = session.get(CheckoutTransaction, unit.get("custom_id") or unit.get("reference_id") or "")
        if tx and tx.status in ("quoted", "locked"):
            capture_and_fulfill(session, tx, resource["id"], background_tasks, client)
    elif etype == "PAYMENT.CAPTURE.COMPLETED":
        tx = session.get(CheckoutTransaction, resource.get("custom_id") or "")
        if tx and tx.status in ("quoted", "locked") and resource.get("supplementary_data"):
            order_id = (resource["supplementary_data"].get("related_ids") or {}).get("order_id")
            if order_id:
                capture_and_fulfill(session, tx, order_id, background_tasks, client)
    elif etype in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.REFUNDED"):
        tx = session.get(CheckoutTransaction, resource.get("custom_id") or "")
        if tx:
            tx.status = "refunded" if etype.endswith("REFUNDED") else "needs_attention"
            session.add(tx)
            session.commit()
            if not etype.endswith("REFUNDED"):
                _alert_owner(f"PayPal {etype.split('.')[-1].lower()} on checkout {tx.id}",
                             "Payment did not stand; review any supplier order for this checkout.")
    return {"status": "ok"}


def refund_checkout(session: Session, checkout_id: str, amount: Optional[float] = None,
                    client: Optional[paypal.PayPalClient] = None) -> dict:
    """Refund a PayPal-paid checkout (full when amount is None). Idempotent per capture+amount."""
    tx = session.get(CheckoutTransaction, checkout_id)
    if tx is None or tx.payment_provider != "paypal" or not tx.payment_capture_id:
        raise ValueError("no PayPal capture to refund for this checkout")
    client = client or paypal.PayPalClient()
    body = client.refund_capture(tx.payment_capture_id, amount=amount, note="Mikisi order refund")
    if amount is None:
        tx.status = "refunded"
        session.add(tx)
        session.commit()
    return body
