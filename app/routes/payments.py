from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from sqlmodel import Session, select
from app.models.cart import CartItem
from app.models.product import Product
from app.models.order import Order
from app.database import get_session, engine
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel
import stripe
import os
import json

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

router = APIRouter()

class CheckoutRequest(BaseModel):
    shipping_address: str
    shipping_method: str = "usps"  # "fast_track" or "usps"

@router.post("/payments/create-checkout")
def create_checkout_session(
    request: CheckoutRequest,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_email = payload.get("sub")

    items = session.exec(
        select(CartItem).where(CartItem.user_id == user_email)
    ).all()

    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    line_items = []
    for item in items:
        product = session.get(Product, item.product_id)
        if product:
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{product.brand} - {product.name}",
                        "description": (product.description or "")[:50],
                    },
                    "unit_amount": int(product.final_price * 100),
                },
                "quantity": item.quantity,
            })

    frontend_url = "https://deniskleindkm-droid.github.io/api-project"

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=f"{frontend_url}?payment=success",
        cancel_url=f"{frontend_url}?payment=cancelled",
        customer_email=user_email,
        metadata={
            "user_email": user_email,
            "shipping_address": request.shipping_address,
            "shipping_method": request.shipping_method,
        }
    )

    return {"checkout_url": checkout_session.url}


class GuestCartItem(BaseModel):
    product_id: int
    quantity: int = 1

class GuestCheckoutRequest(BaseModel):
    items: list[GuestCartItem]
    email: str
    first_name: str
    last_name: str
    shipping_address: str
    shipping_method: str = "usps"


@router.post("/payments/guest-checkout")
def create_guest_checkout_session(
    request: GuestCheckoutRequest,
    session: Session = Depends(get_session),
):
    if not request.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    line_items = []
    items_meta = []
    for item in request.items:
        product = session.get(Product, item.product_id)
        if not product or not product.is_active or not product.is_published:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} is no longer available")
        if product.stock == 0:
            raise HTTPException(status_code=400, detail=f"'{product.name[:40]}' is out of stock")
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Mikisi — {product.name[:50]}",
                    "description": (product.description or "")[:50],
                },
                "unit_amount": int(product.final_price * 100),
            },
            "quantity": item.quantity,
        })
        items_meta.append({"product_id": product.id, "quantity": item.quantity})

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url="https://mikisi.co/?payment=success",
        cancel_url="https://mikisi.co/",
        customer_email=request.email,
        metadata={
            "user_email":       request.email,
            "first_name":       request.first_name,
            "last_name":        request.last_name,
            "shipping_address": request.shipping_address,
            "shipping_method":  request.shipping_method,
            "guest_items":      json.dumps(items_meta),
            "is_guest":         "true",
        },
    )
    return {"checkout_url": checkout_session.url}


def process_order_background(checkout_data: dict):
    try:
        user_email = checkout_data["metadata"]["user_email"]
        shipping_address = checkout_data["metadata"]["shipping_address"]
        shipping_method = checkout_data["metadata"].get("shipping_method", "usps")
        is_guest = checkout_data["metadata"].get("is_guest") == "true"
        first_name = checkout_data["metadata"].get("first_name", "")
        last_name = checkout_data["metadata"].get("last_name", "")
        guest_items_raw = checkout_data["metadata"].get("guest_items", "[]")

        order_details = []
        total = 0

        with Session(engine) as session:
            if is_guest:
                guest_items = json.loads(guest_items_raw)
                print(f"[Payments] Guest order — {len(guest_items)} item(s) for {user_email}")
                for item_data in guest_items:
                    product = session.get(Product, item_data["product_id"])
                    qty = item_data.get("quantity", 1)
                    if product:
                        subtotal = product.final_price * qty
                        total += subtotal
                        order_details.append({
                            "name": product.name,
                            "qty": qty,
                            "price": product.final_price,
                            "subtotal": subtotal,
                            "supplier": product.supplier_name,
                            "supplier_url": product.supplier_url,
                            "product_id": product.id,
                            "cj_sku": product.cj_sku,
                            "cj_product_id": product.cj_product_id,
                        })
                        print(f"[Payments] Guest item: {product.name} — CJ SKU: {product.cj_sku}")
                        order = Order(
                            user_id=user_email,
                            guest_email=user_email,
                            is_guest=True,
                            product_id=product.id,
                            quantity=qty,
                            total_price=subtotal,
                            status="paid",
                            shipping_address=shipping_address,
                            shipping_method=shipping_method,
                        )
                        product.stock -= qty
                        session.add(order)
                        session.add(product)
                session.commit()
            else:
                cart_items = session.exec(
                    select(CartItem).where(CartItem.user_id == user_email)
                ).all()

                print(f"[Payments] Found {len(cart_items)} cart items for {user_email}")

                if not cart_items:
                    print(f"[Payments] Cart already empty for {user_email} — webhook retry or already processed. Skipping.")
                    return

                for item in cart_items:
                    product = session.get(Product, item.product_id)
                    if product:
                        subtotal = product.final_price * item.quantity
                        total += subtotal
                        order_details.append({
                            "name": product.name,
                            "qty": item.quantity,
                            "price": product.final_price,
                            "subtotal": subtotal,
                            "supplier": product.supplier_name,
                            "supplier_url": product.supplier_url,
                            "product_id": item.product_id,
                            "cj_sku": product.cj_sku,
                            "cj_product_id": product.cj_product_id,
                        })
                        print(f"[Payments] Item: {product.name} — CJ SKU: {product.cj_sku}")
                        order = Order(
                            user_id=user_email,
                            product_id=item.product_id,
                            quantity=item.quantity,
                            total_price=subtotal,
                            status="paid",
                            shipping_address=shipping_address,
                            shipping_method=shipping_method,
                        )
                        product.stock -= item.quantity
                        session.add(order)
                        session.add(product)
                        session.delete(item)

                session.commit()

        print(f"[Payments] Order details collected: {len(order_details)} items, total ${total:.2f}")

        # Auto-forward to Silverbene
        try:
            from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
            from app.agents.tracking_agent import create_tracking_entry
            silverbene = SilverbeneAdapter()

            print(f"[Payments] Starting Silverbene forwarding for {len(order_details)} items")

            if first_name:
                customer_first = first_name.capitalize()
                customer_last  = last_name.capitalize() if last_name else "Customer"
            else:
                customer_name_parts = user_email.split("@")[0].split(".")
                customer_first = customer_name_parts[0].capitalize()
                customer_last  = customer_name_parts[1].capitalize() if len(customer_name_parts) > 1 else "Customer"

            # Parse shipping_address string into structured fields
            # Expected format: "123 Street, City, State, ZIP, Country"
            def _parse_address(addr_str: str) -> dict:
                parts = [p.strip() for p in addr_str.split(",")]
                return {
                    "line1":        parts[0] if len(parts) > 0 else "",
                    "city":         parts[1] if len(parts) > 1 else "",
                    "state":        parts[2] if len(parts) > 2 else "",
                    "state_code":   parts[2][:2].upper() if len(parts) > 2 else "",
                    "postal_code":  parts[3].strip() if len(parts) > 3 else "",
                    "country_code": parts[4].strip().upper() if len(parts) > 4 else "US",
                }

            address = _parse_address(shipping_address)

            customer = {
                "first_name": customer_first,
                "last_name":  customer_last,
                "email":      "hello@mikisi.co",  # never send real customer email to supplier
                "phone":      "",
            }

            # Get saved orders for tracking linkage
            with Session(engine) as session:
                saved_orders = session.exec(
                    select(Order).where(
                        Order.user_id == user_email,
                        Order.status == "paid"
                    ).order_by(Order.id.desc()).limit(len(order_details))
                ).all()

            # Pre-flight: check Silverbene balance before placing any orders.
            # If balance is critically low (<$20), hold all orders as pending_credit
            # rather than letting Silverbene send payment requests.
            sb_balance = silverbene.check_balance()
            balance_ok = sb_balance < 0 or sb_balance >= 20  # -1 means API unavailable → proceed
            if sb_balance >= 0 and sb_balance < 50:
                # Warn Dennis proactively (not critical yet, but worth knowing)
                silverbene._alert_low_credit(
                    subject=f"⚠️ Silverbene balance low: ${sb_balance:.2f}",
                    body=(
                        f"<p>Your Silverbene store credit is <b>${sb_balance:.2f}</b>. "
                        f"Top up now to avoid order failures.</p>"
                        f"<p>Contact Jacky: <a href='mailto:jackyli@silverbene.com'>jackyli@silverbene.com</a> "
                        f"or WhatsApp +86 180 2239 4913</p>"
                    ),
                )
            print(f"[Payments] Silverbene balance: {'${:.2f}'.format(sb_balance) if sb_balance >= 0 else 'unknown'} — proceed={balance_ok}")

            for i, d in enumerate(order_details):
                option_id = d.get("cj_sku")   # cj_sku stores Silverbene option_id
                sku       = d.get("cj_product_id")
                db_order_id = saved_orders[i].id if saved_orders and i < len(saved_orders) else (saved_orders[0].id if saved_orders else None)
                print(f"[Payments] Forwarding to Silverbene: {d['name']} | option_id={option_id}")

                if not option_id:
                    print(f"[Payments] No Silverbene option_id for {d['name']} — manual fulfillment needed")
                    continue

                # If balance is critically low, hold order instead of risking a Silverbene payment request
                if not balance_ok and db_order_id:
                    with Session(engine) as session:
                        order_rec = session.get(Order, db_order_id)
                        if order_rec:
                            order_rec.status = "pending_credit"
                            session.add(order_rec)
                            session.commit()
                    silverbene._alert_low_credit(
                        subject=f"❌ Order #{db_order_id} held — Silverbene balance too low (${sb_balance:.2f})",
                        body=(
                            f"<p>Order <b>#{db_order_id}</b> for <b>{d['name']}</b> could not be sent to Silverbene "
                            f"because your store credit is <b>${sb_balance:.2f}</b> — below the $20 safety threshold.</p>"
                            f"<p>The customer has been charged and will receive a confirmation email from Mikisi. "
                            f"The order will be retried automatically every 2 hours once your balance is topped up.</p>"
                            f"<p><b>Top up now:</b> Contact Jacky at "
                            f"<a href='mailto:jackyli@silverbene.com'>jackyli@silverbene.com</a></p>"
                        ),
                    )
                    print(f"[Payments] Order #{db_order_id} held as pending_credit — balance ${sb_balance:.2f}")
                    continue

                result = silverbene.place_order(
                    product_id=str(option_id),
                    customer=customer,
                    address=address,
                    quantity=d["qty"],
                    option_id=str(option_id),
                )
                print(f"[Payments] Silverbene order result: {result}")

                if result.get("success") and db_order_id:
                    create_tracking_entry(
                        order_id=db_order_id,
                        cj_order_id=result.get("supplier_order_id", ""),
                        customer_email=user_email,
                        customer_name=f"{customer_first} {customer_last}",
                        supplier_name="Silverbene"
                    )
                    with Session(engine) as session:
                        order_rec = session.get(Order, db_order_id)
                        if order_rec:
                            order_rec.status = "processing"
                            order_rec.supplier_notified = True
                            session.add(order_rec)
                            session.commit()
                elif not result.get("success"):
                    reason = result.get("reason", "unknown error")
                    print(f"[Payments] Silverbene rejected order for {d['name']}: {reason}")
                    if "insufficient_credit" in reason and db_order_id:
                        with Session(engine) as session:
                            order_rec = session.get(Order, db_order_id)
                            if order_rec:
                                order_rec.status = "pending_credit"
                                session.add(order_rec)
                                session.commit()
        except Exception as e:
            print(f"[Payments] Silverbene forwarding failed: {e}")

        # Build items HTML for emails
        items_html = "".join([
            f"<tr><td>{d['name']}</td><td>{d['qty']}</td><td>${d['price']:.2f}</td><td>${d['subtotal']:.2f}</td></tr>"
            for d in order_details
        ])

        items_html_customer = "".join([
            f"<tr><td style='padding:10px 0;font-size:14px;font-weight:300;color:#0e0e0e;border-bottom:1px solid #ece5dd;'>{d['name']}</td><td style='text-align:center;padding:10px 0;font-size:14px;font-weight:300;color:#6b6b6b;border-bottom:1px solid #ece5dd;'>{d['qty']}</td><td style='text-align:right;padding:10px 0;font-family:Georgia,serif;font-size:16px;color:#0e0e0e;border-bottom:1px solid #ece5dd;'>${d['subtotal']:.2f}</td></tr>"
            for d in order_details
        ])

        # Send email notification to Dennis
        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL")

            send_email(
                to=dennis_email,
                subject=f"New Mikisi Order — ${total:.2f}",
                body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#d4849c;">New Order Received!</h2>
<p><strong>Customer:</strong> {user_email}</p>
<p><strong>Shipping Address:</strong> {shipping_address}</p>
<h3>Order Details:</h3>
<table border="1" cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;">
<tr style="background:#f5f5f5;">
    <th>Product</th><th>Qty</th><th>Price</th><th>Subtotal</th>
</tr>
{items_html}
<tr style="background:#fff5f7;">
    <td colspan="3"><strong>Total</strong></td>
    <td><strong>${total:.2f}</strong></td>
</tr>
</table>
<br>
<p style="color:#d4849c;font-weight:bold;">Silverbene order forwarding attempted automatically.</p>
<p>Ship to: {shipping_address}</p>
</body></html>""",
                is_html=True
            )
            print(f"[Payments] Order notification sent to Dennis — ${total:.2f}")
        except Exception as e:
            print(f"[Payments] Dennis email failed: {e}")

        # Send confirmation email to customer
        try:
            from app.agents.email_partner import send_email
            send_email(
                to=user_email,
                subject="Your Mikisi Order is Confirmed ✨",
                body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#fdf9f6;">
<div style="text-align:center;padding:32px 0;">
    <h1 style="font-family:Georgia,serif;color:#0e0e0e;letter-spacing:4px;text-transform:uppercase;font-size:28px;font-weight:300;">Mik<em style="color:#d4849c;">i</em>si</h1>
    <p style="font-size:11px;color:#888;letter-spacing:3px;text-transform:uppercase;">Look Elegant and Polished</p>
</div>
<div style="background:white;padding:32px;border:1px solid #ece5dd;">
    <h2 style="font-family:Georgia,serif;font-weight:300;font-size:24px;color:#0e0e0e;margin-bottom:8px;">Your order is confirmed.</h2>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">Thank you for your purchase. We're preparing your order and it will be on its way soon.</p>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:16px;">Order Summary</h3>
    <table style="width:100%;border-collapse:collapse;">
        <tr style="border-bottom:1px solid #ece5dd;">
            <th style="text-align:left;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Product</th>
            <th style="text-align:center;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Qty</th>
            <th style="text-align:right;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Price</th>
        </tr>
        {items_html_customer}
        <tr>
            <td colspan="2" style="padding:16px 0 8px;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#888;">Total</td>
            <td style="padding:16px 0 8px;text-align:right;font-family:Georgia,serif;font-size:20px;color:#0e0e0e;">${total:.2f}</td>
        </tr>
    </table>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:12px;">Shipping To</h3>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">{shipping_address}</p>
    <p style="color:#6b6b6b;font-size:13px;font-weight:300;margin-top:16px;">Estimated delivery: 8–10 business days via USPS</p>
</div>
<div style="text-align:center;padding:32px 0;">
    <p style="font-size:11px;color:#bbb;letter-spacing:1px;">Questions? Contact us at hello@mikisi.co</p>
    <p style="font-size:10px;color:#ccc;margin-top:8px;letter-spacing:1px;">© 2026 Mikisi · Look Elegant and Polished</p>
</div>
</body></html>""",
                is_html=True
            )
            print(f"[Payments] Customer confirmation sent to {user_email}")
        except Exception as e:
            print(f"[Payments] Customer email failed: {e}")

    except Exception as e:
        print(f"[Payments] Background processing failed: {e}")


def _stripe_meta(obj, key: str, default: str = "") -> str:
    try:
        return obj[key]
    except (KeyError, TypeError):
        return default


@router.post("/payments/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            print("[Payments] WARNING: STRIPE_WEBHOOK_SECRET not set — skipping signature verification")
            event = json.loads(payload)
    except stripe.error.SignatureVerificationError as e:
        print(f"[Payments] Webhook signature mismatch — check STRIPE_WEBHOOK_SECRET in Railway: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"[Payments] Webhook parse error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        raw = getattr(obj, "metadata", None) or {}
        metadata = {
            "user_email":       _stripe_meta(raw, "user_email"),
            "shipping_address": _stripe_meta(raw, "shipping_address"),
            "shipping_method":  _stripe_meta(raw, "shipping_method", "usps"),
            "is_guest":         _stripe_meta(raw, "is_guest"),
            "guest_items":      _stripe_meta(raw, "guest_items"),
            "first_name":       _stripe_meta(raw, "first_name"),
            "last_name":        _stripe_meta(raw, "last_name"),
        }
        background_tasks.add_task(process_order_background, {"metadata": metadata})

    return {"status": "ok"}


@router.post("/payments/recover-order/{session_id}")
async def recover_missed_order(
    session_id: str,
    background_tasks: BackgroundTasks,
    master_key: str = "",
    token: str = Depends(oauth2_scheme)
):
    """
    Admin endpoint: manually replay a Stripe checkout session that the webhook missed.
    Use this when a customer paid but the order wasn't recorded.
    """
    from app.agents.aria_security import verify_master_key
    payload = verify_token(token)
    if not payload and not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        checkout_obj = stripe.checkout.Session.retrieve(session_id)
        if getattr(checkout_obj, "payment_status", None) != "paid":
            raise HTTPException(status_code=400, detail="Session not paid yet")
        raw = getattr(checkout_obj, "metadata", None) or {}
        metadata = {
            "user_email":       _stripe_meta(raw, "user_email"),
            "shipping_address": _stripe_meta(raw, "shipping_address"),
            "shipping_method":  _stripe_meta(raw, "shipping_method", "usps"),
        }
        background_tasks.add_task(process_order_background, {"metadata": metadata})
        return {"status": "recovery_started", "session_id": session_id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))