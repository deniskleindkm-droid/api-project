from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.models.cart import CartItem
from app.models.product import Product
from app.database import get_session
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class CartRequest(BaseModel):
    product_id: int
    quantity: int = 1
    selected_size: Optional[str] = None
    selected_color: Optional[str] = None
    selected_option_id: Optional[str] = None

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
    # Mirrors _require_published_or_preview in routes/products.py — a
    # customer should never be able to add an unpublished or hidden-
    # category product to their cart just because they know its ID
    # (found live 2026-07-17: the product page itself was already gated,
    # but this endpoint had no idea and would accept any product_id).
    from app.agents.store_config import get_hidden_categories
    if not product.is_published or product.category in get_hidden_categories():
        raise HTTPException(status_code=404, detail="Product not found")

    # Same product + same size + same color = increment quantity
    # Same product + different variant = separate line item
    query = select(CartItem).where(
        CartItem.user_id == payload.get("sub"),
        CartItem.product_id == item.product_id,
        CartItem.selected_size == item.selected_size,
        CartItem.selected_color == item.selected_color,
    )
    existing = session.exec(query).first()

    if existing:
        existing.quantity += item.quantity
        # A newer add-to-cart always carries a freshly-resolved option_id (or a
        # more current one) — prefer it over whatever an older click stored.
        if item.selected_option_id:
            existing.selected_option_id = item.selected_option_id
        session.add(existing)
    else:
        session.add(CartItem(
            user_id=payload.get("sub"),
            product_id=item.product_id,
            quantity=item.quantity,
            selected_size=item.selected_size,
            selected_color=item.selected_color,
            selected_option_id=item.selected_option_id,
        ))

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
    removed = 0
    for item in items:
        product = session.get(Product, item.product_id)
        unavailable = (
            not product
            or not product.is_active
            or not product.is_published
        )
        if unavailable:
            session.delete(item)
            removed += 1
            continue
        out_of_stock = product.stock == 0
        subtotal = product.final_price * item.quantity
        if not out_of_stock:
            total += subtotal
        result.append({
            "cart_item_id": item.id,
            "product_id": product.id,
            "name": product.name,
            "brand": product.brand,
            "price": product.final_price,
            "quantity": item.quantity,
            "subtotal": subtotal,
            "image_url": product.image_url,
            "content_image_url": product.content_image_url,
            "selected_size": item.selected_size,
            "selected_color": item.selected_color,
            "selected_option_id": item.selected_option_id,
            "out_of_stock": out_of_stock,
        })

    if removed:
        session.commit()

    return {"items": result, "total": total, "removed_count": removed}


@router.get("/cart/validate")
def validate_cart_items(ids: str, session: Session = Depends(get_session)):
    """Public — guest cart validation. ids=1,2,3 comma-separated product IDs."""
    try:
        product_ids = [int(i.strip()) for i in ids.split(",") if i.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers")

    result = {}
    for pid in product_ids:
        product = session.get(Product, pid)
        if not product or not product.is_active or not product.is_published:
            result[pid] = {"available": False, "out_of_stock": False}
        else:
            result[pid] = {"available": True, "out_of_stock": product.stock == 0}
    return result

@router.delete("/cart/{cart_item_id}")
def remove_from_cart(cart_item_id: int, session: Session = Depends(get_session), token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    item = session.get(CartItem, cart_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if item.quantity > 1:
        item.quantity -= 1
        session.add(item)
        session.commit()
        return {"message": "Quantity reduced", "quantity": item.quantity}
    else:
        session.delete(item)
        session.commit()
        return {"message": "Item removed"}

