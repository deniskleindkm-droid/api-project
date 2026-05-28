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
            "shipping_address": request.shipping_address
        }
    )

    return {"checkout_url": checkout_session.url}


def process_order_background(checkout_data: dict):
    try:
        user_email = checkout_data["metadata"]["user_email"]
        shipping_address = checkout_data["metadata"]["shipping_address"]

        order_details = []
        total = 0

        with Session(engine) as session:
            cart_items = session.exec(
                select(CartItem).where(CartItem.user_id == user_email)
            ).all()

            print(f"[Payments] Found {len(cart_items)} cart items for {user_email}")

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
                        shipping_address=shipping_address
                    )
                    product.stock -= item.quantity
                    session.add(order)
                    session.add(product)
                    session.delete(item)

            session.commit()

        print(f"[Payments] Order details collected: {len(order_details)} items, total ${total:.2f}")

        # Auto-forward to CJ Dropshipping
        try:
            from app.agents.cj_dropshipping import place_order_on_cj
            from app.agents.tracking_agent import create_tracking_entry
            print(f"[Payments] Starting CJ forwarding for {len(order_details)} items")

            # Get customer name from email
            customer_name = user_email.split("@")[0]

            # Get the saved orders to link tracking
            with Session(engine) as session:
                saved_orders = session.exec(
                    select(Order).where(
                        Order.user_id == user_email,
                        Order.status == "paid"
                    ).order_by(Order.id.desc()).limit(len(order_details))
                ).all()

            for i, d in enumerate(order_details):
                print(f"[Payments] Checking SKU for {d['name']}: {d.get('cj_sku')}")
                if d.get("cj_sku"):
                    cj_result = place_order_on_cj(
                        cj_sku=d["cj_sku"],
                        customer_name=customer_name,
                        shipping_address=shipping_address,
                        quantity=d["qty"]
                    )
                    print(f"[Payments] CJ order result: {cj_result}")

                    # Create tracking entry if order placed successfully
                    if cj_result.get("success") and saved_orders:
                        order_id = saved_orders[i].id if i < len(saved_orders) else saved_orders[0].id
                        create_tracking_entry(
                            order_id=order_id,
                            cj_order_id=cj_result.get("cj_order_id", ""),
                            customer_email=user_email,
                            customer_name=customer_name,
                            supplier_name="CJDropshipping"
                        )
                else:
                    print(f"[Payments] No CJ SKU for: {d['name']} — manual fulfillment needed")
        except Exception as e:
            print(f"[Payments] CJ forwarding failed: {e}")

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
<p style="color:#d4849c;font-weight:bold;">CJ order forwarding attempted automatically.</p>
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
    <p style="color:#6b6b6b;font-size:13px;font-weight:300;margin-top:16px;">Estimated delivery: 15-20 business days</p>
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


@router.post("/payments/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        checkout_data = event["data"]["object"]
        background_tasks.add_task(process_order_background, checkout_data)

    return {"status": "ok"}