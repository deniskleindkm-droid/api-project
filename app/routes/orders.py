from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.models.order import Order
from app.models.product import Product
from app.database import get_session
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from typing import Optional

router = APIRouter()

class OrderCreate:
    def __init__(self, product_id: int, quantity: int, shipping_address: str):
        self.product_id = product_id
        self.quantity = quantity
        self.shipping_address = shipping_address

from pydantic import BaseModel

class OrderRequest(BaseModel):
    product_id: int
    quantity: int = 1
    shipping_address: str

@router.post("/orders")
def create_order(
    order: OrderRequest,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    product = session.get(Product, order.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock < order.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")
    
    total = product.final_price * order.quantity
    
    new_order = Order(
        user_id=payload.get("sub"),
        product_id=order.product_id,
        quantity=order.quantity,
        total_price=total,
        status="pending"
    )
    
    product.stock -= order.quantity
    session.add(product)
    session.add(new_order)
    session.commit()
    session.refresh(new_order)
    return new_order

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