from fastapi import APIRouter, HTTPException, Depends, Request
from sqlmodel import Session, select
from app.models.cart import CartItem
from app.models.product import Product
from app.models.order import Order
from app.database import get_session
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel
import stripe
import os

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
                        "description": product.description,
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

@router.post("/payments/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    
    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            import json
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    if event["type"] == "checkout.session.completed":
        checkout = event["data"]["object"]
        user_email = checkout["metadata"]["user_email"]
        shipping_address = checkout["metadata"]["shipping_address"]
        
        cart_items = session.exec(
            select(CartItem).where(CartItem.user_id == user_email)
        ).all()
        
        for item in cart_items:
            product = session.get(Product, item.product_id)
            if product:
                order = Order(
                    user_id=user_email,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    total_price=product.final_price * item.quantity,
                    status="paid",
                    shipping_address=shipping_address
                )
                product.stock -= item.quantity
                session.add(product)
                session.add(order)
                session.delete(item)
        
        session.commit()
    
    return {"status": "ok"}