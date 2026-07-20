from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.models.order import Order, OrderTracking
from app.models.product import Product
from app.database import get_session
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

class OrderCreate:
    def __init__(self, product_id: int, quantity: int, shipping_address: str):
        self.product_id = product_id
        self.quantity = quantity
        self.shipping_address = shipping_address

class MarkShippedRequest(BaseModel):
    master_key: str
    tracking_number: str
    carrier: str = "USPS"


@router.post("/admin/orders/{order_id}/mark-shipped")
def mark_order_shipped(order_id: int, data: MarkShippedRequest, session: Session = Depends(get_session)):
    """
    Admin — call this when Silverbene sends a shipping notification to hello@mikisi.co.
    Updates tracking and sends the Mikisi branded shipping email to the real customer.
    """
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    tracking = session.exec(
        select(OrderTracking).where(OrderTracking.order_id == order_id)
    ).first()

    if not tracking:
        raise HTTPException(status_code=404, detail=f"No tracking record for order {order_id}")

    tracking.tracking_number = data.tracking_number
    tracking.carrier = data.carrier
    tracking.status = "dispatched"
    tracking.shipped_at = datetime.utcnow()
    session.add(tracking)
    session.commit()
    session.refresh(tracking)

    email_sent = False
    if not tracking.shipping_notified and tracking.customer_email:
        from app.agents.tracking_agent import send_shipping_email
        email_sent = send_shipping_email(tracking)
        if email_sent:
            tracking.shipping_notified = True
            session.add(tracking)
            session.commit()

    order = session.get(Order, order_id)
    if order:
        order.status = "shipped"
        order.tracking_number = data.tracking_number
        session.add(order)
        session.commit()

    return {
        "order_id": order_id,
        "tracking_number": data.tracking_number,
        "carrier": data.carrier,
        "customer_email": tracking.customer_email,
        "shipping_email_sent": email_sent,
    }


@router.get("/admin/orders")
def get_all_orders(master_key: str, session: Session = Depends(get_session)):
    """Admin — list all orders with tracking status."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    orders = session.exec(select(Order).order_by(Order.id.desc()).limit(50)).all()
    result = []
    for o in orders:
        tracking = session.exec(
            select(OrderTracking).where(OrderTracking.order_id == o.id)
        ).first()
        result.append({
            "id": o.id,
            "customer_email": o.guest_email or o.user_id,
            "status": o.status,
            "total": o.total_price,
            "created_at": o.created_at.isoformat(),
            "tracking_number": tracking.tracking_number if tracking else None,
            "carrier": tracking.carrier if tracking else None,
            "tracking_status": tracking.status if tracking else None,
            "shipping_notified": tracking.shipping_notified if tracking else False,
        })
    return result


@router.get("/orders")
def get_my_orders(
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    orders = session.exec(
        select(Order).where(Order.user_id == payload.get("sub"))
    ).all()
    return orders

@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != payload.get("sub"):
        raise HTTPException(status_code=403, detail="Not your order")
    return order