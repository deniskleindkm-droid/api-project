from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import Session, select
from app.models.product import Product, ProductCreate, ProductPublic
from app.database import get_session
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter()


# ── HERO BANNER ───────────────────────────────────────────────────────────────

class HeroUpdate(BaseModel):
    banner_url: Optional[str] = None    # direct URL (CDN, Cloudinary, etc.)
    banner_b64: Optional[str] = None    # base64 encoded image for direct upload
    tagline: Optional[str] = None
    master_key: str

@router.get("/store/hero")
def get_hero():
    """Public — returns current hero banner URL and tagline for the storefront."""
    from app.agents.store_config import get_config
    return {
        "banner_url": get_config("hero_banner_url", default="") or None,
        "tagline": get_config("hero_tagline", default="Crafted with love. Worn with confidence."),
    }

@router.put("/store/hero")
def update_hero(data: HeroUpdate):
    """Command Center — update the hero banner URL/image and tagline."""
    import os
    from app.agents.store_config import set_config
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if data.banner_url is not None:
        set_config("hero_banner_url", data.banner_url, "Hero banner image URL")
    elif data.banner_b64 is not None:
        # Store base64 directly — small images only (< 500KB after encoding)
        if len(data.banner_b64) > 700_000:
            raise HTTPException(status_code=400, detail="Image too large — use a URL instead (host on Cloudinary or Imgur)")
        set_config("hero_banner_url", data.banner_b64, "Hero banner image base64")

    if data.tagline is not None:
        set_config("hero_tagline", data.tagline, "Hero banner tagline text")

    return {"status": "updated", "message": "Banner updated — refresh the storefront to see it live"}

@router.get("/products", response_model=List[ProductPublic])
def get_products(
    brand: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    session: Session = Depends(get_session)
):
    query = select(Product).where(Product.is_active == True)

    if brand:
        query = query.where(Product.brand == brand)
    if category:
        query = query.where(Product.category == category)
    if min_price:
        query = query.where(Product.final_price >= min_price)
    if max_price:
        query = query.where(Product.final_price <= max_price)

    products = session.exec(query).all()
    return products

@router.get("/products/{product_id}", response_model=ProductPublic)
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/products")
def create_product(product: ProductCreate, session: Session = Depends(get_session)):
    db_product = Product(**product.dict())
    session.add(db_product)
    session.commit()
    session.refresh(db_product)
    return db_product
@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    data: dict,
    session: Session = Depends(get_session)
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in data.items():
        if hasattr(product, key):
            setattr(product, key, value)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product

@router.get("/shipping-options")
def get_shipping_options():
    """Public endpoint — returns the two shipping tiers (Fast Track + USPS) for product panels and checkout."""
    from app.agents.store_config import get_config
    tiers = []
    for key in ["express", "standard"]:  # only these two — no economy
        label   = get_config(f"shipping_{key}_label",   default=key.title())
        days    = get_config(f"shipping_{key}_days",    default="")
        carrier = get_config(f"shipping_{key}_carrier", default="")
        if days:
            tiers.append({"key": key, "label": label, "days": days, "carrier": carrier})
    return {"tiers": tiers}


@router.delete("/products/{product_id}")
def delete_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    session.add(product)
    session.commit()
    return {"message": "Product removed successfully"}

@router.get("/brands")
def get_brands(session: Session = Depends(get_session)):
    products = session.exec(select(Product).where(Product.is_active == True)).all()
    brands = list(set([p.brand for p in products]))
    return {"brands": sorted(brands)}

@router.get("/categories")
def get_categories(session: Session = Depends(get_session)):
    products = session.exec(select(Product).where(Product.is_active == True)).all()
    categories = list(set([p.category for p in products]))
    return {"categories": sorted(categories)}

@router.put("/products/{product_id}/collection")
def assign_collection(
    product_id: int,
    collection_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.collection_id = collection_id
    session.add(product)
    session.commit()
    session.refresh(product)
    return {"product_id": product_id, "collection_id": collection_id, "message": "Collection assigned"}