from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.models.cart import CartItem
from app.models.product import Product
from app.database import get_session
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel

router = APIRouter()

class CartRequest(BaseModel):
    product_id: int
    quantity: int = 1

@router.post("/cart")
def add_to_cart(
    item: CartRequest,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    product = session.get(Product, item.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock < item.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")
    
    existing = session.exec(
        select(CartItem).where(
            CartItem.user_id == payload.get("sub"),
            CartItem.product_id == item.product_id
        )
    ).first()
    
    if existing:
        existing.quantity += item.quantity
        session.add(existing)
    else:
        cart_item = CartItem(
            user_id=payload.get("sub"),
            product_id=item.product_id,
            quantity=item.quantity
        )
        session.add(cart_item)
    
    session.commit()
    return {"message": "Added to cart"}

@router.get("/cart")
def get_cart(
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    items = session.exec(
        select(CartItem).where(CartItem.user_id == payload.get("sub"))
    ).all()
    
    result = []
    total = 0
    for item in items:
        product = session.get(Product, item.product_id)
        if product:
            subtotal = product.final_price * item.quantity
            total += subtotal
            result.append({
                "cart_item_id": item.id,
                "product_id": product.id,
                "name": product.name,
                "brand": product.brand,
                "price": product.final_price,
                "quantity": item.quantity,
                "subtotal": subtotal,
                "image_url": product.image_url
            })
    
    return {"items": result, "total": total}

@router.delete("/cart/{cart_item_id}")
def remove_from_cart(
    cart_item_id: int,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    item = session.get(CartItem, cart_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.user_id != payload.get("sub"):
        raise HTTPException(status_code=403, detail="Not your cart")
    
    session.delete(item)
    session.commit()
    return {"message": "Item removed from cart"}

@router.post("/cart/checkout")
def checkout(
    shipping_address: str,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    from app.models.order import Order
    
    items = session.exec(
        select(CartItem).where(CartItem.user_id == payload.get("sub"))
    ).all()
    
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    orders = []
    for item in items:
        product = session.get(Product, item.product_id)
        if product and product.stock >= item.quantity:
            order = Order(
                user_id=payload.get("sub"),
                product_id=item.product_id,
                quantity=item.quantity,
                total_price=product.final_price * item.quantity,
                status="pending",
                shipping_address=shipping_address
            )
            product.stock -= item.quantity
            session.add(product)
            session.add(order)
            session.delete(item)
            orders.append(order)
    
    session.commit()
    return {"message": "Order placed successfully", "orders_created": len(orders)}