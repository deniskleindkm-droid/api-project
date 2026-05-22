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

        # Auto-forward to CJ Dropshipping
        try:
            from app.agents.cj_dropshipping import place_order_on_cj
            for d in order_details:
                if d.get("cj_sku"):
                    cj_result = place_order_on_cj(
                        cj_sku=d["cj_sku"],
                        customer_name=user_email.split("@")[0],
                        shipping_address=shipping_address,
                        quantity=d["qty"]
                    )
                    print(f"[Payments] CJ order result: {cj_result}")
                else:
                    print(f"[Payments] No CJ SKU for: {d['name']} — manual fulfillment needed")
        except Exception as e:
            print(f"[Payments] CJ forwarding failed: {e}")

        # Send email notification
        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL")

            items_html = "".join([
                f"<tr><td>{d['name']}</td><td>{d['qty']}</td><td>${d['price']:.2f}</td><td>${d['subtotal']:.2f}</td></tr>"
                for d in order_details
            ])

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
            print(f"[Payments] Order notification sent — ${total:.2f}")
        except Exception as e:
            print(f"[Payments] Email failed: {e}")

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