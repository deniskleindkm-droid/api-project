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
    """Public — returns hero banner image, video, and tagline for the storefront."""
    from app.agents.store_config import get_config
    return {
        "banner_url": get_config("hero_banner_url", default="") or None,
        "video_url":  get_config("hero_video_url",  default="") or None,
        "tagline":    get_config("hero_tagline", default="Crafted with love. Worn with confidence."),
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
    query = select(Product).where(
        Product.is_active == True,
        Product.is_published == True,
    )

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


@router.get("/products/{product_id}/variant-prices")
def get_variant_prices(product_id: int, session: Session = Depends(get_session)):
    """
    Return per-variant pricing for a product.
    Used by the frontend to update the displayed price when a customer
    selects a size or color.

    Response: list of {option_id, size, color, final_price, stock}
    Only includes variants with a known base_price.
    """
    import json as _json
    from app.agents.jewelry_pricing import calculate_mikisi_price
    from app.agents.suppliers.silverbene_adapter import (
        _normalize_size_for_match, _normalize_color_final,
        _clean_color_value, COLOR_ATTRIBUTE_NAMES, parse_necklace_length,
    )

    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    try:
        variants = _json.loads(product.variants or "[]")
    except Exception:
        return []

    result = []
    for v in variants:
        bp = v.get("base_price") or v.get("price")
        if not bp:
            continue
        bp = float(bp)
        final_price = calculate_mikisi_price(bp)["final_price"]

        attrs = v.get("attribute") or v.get("attributes") or []
        size = None
        color = None
        for a in attrs:
            name = (a.get("name") or "").lower().strip()
            val  = (a.get("value") or "").strip()
            if name in ("size", "ring size", "bracelet size", "anklet size"):
                size = _normalize_size_for_match(val)
                # Also parse mm/cm length values stored as size (e.g. necklace lengths)
                if not size and val:
                    chips = parse_necklace_length(val)
                    size = chips[0] if chips else None
            elif name in ("chain length", "length") and val:
                # Necklace / bracelet chain length stored in its own attribute
                chips = parse_necklace_length(val)
                if chips:
                    size = chips[0]
            elif name in COLOR_ATTRIBUTE_NAMES:
                # Use the same fully-normalized value that p.colors stores —
                # _normalize_color_final turns "Rhodium"→"Silver", "Pink"→"Rose Gold", etc.
                color = _normalize_color_final(_clean_color_value(val), name)

        result.append({
            "option_id":   v.get("option_id"),
            "size":        size,
            "color":       color,
            "base_price":  round(bp, 2),
            "final_price": final_price,
            "stock":       v.get("qty", 0),
        })

    return result

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

class PublishRequest(BaseModel):
    master_key: str
    product_ids: Optional[List[int]] = None   # None = apply to all in category
    category: Optional[str] = None            # target a whole collection at once
    default_stock: Optional[int] = None       # used by restore endpoint only


@router.post("/admin/products/publish")
def publish_products(data: PublishRequest, session: Session = Depends(get_session)):
    """Admin — publish one product, a batch, or an entire collection."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    query = select(Product)
    if data.product_ids:
        query = query.where(Product.id.in_(data.product_ids))
    elif data.category:
        query = query.where(Product.category == data.category)
    else:
        raise HTTPException(status_code=400, detail="Provide product_ids or category")

    products = session.exec(query).all()
    eligible = [p for p in products if p.stock > 0]  # never publish OOS products
    for p in eligible:
        p.is_published = True
        session.add(p)
    session.commit()
    return {"published": len(eligible), "ids": [p.id for p in eligible]}


@router.post("/admin/products/restore")
def restore_products(data: PublishRequest, session: Session = Depends(get_session)):
    """Admin — restore soft-deleted (is_active=False) products by id list or category."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    query = select(Product)
    if data.product_ids:
        query = query.where(Product.id.in_(data.product_ids))
    elif data.category:
        query = query.where(Product.category == data.category)
    else:
        raise HTTPException(status_code=400, detail="Provide product_ids or category")

    products = session.exec(query).all()
    for p in products:
        p.is_active = True
        if data.default_stock is not None:
            p.stock = data.default_stock
        session.add(p)
    session.commit()
    return {"restored": len(products), "ids": [p.id for p in products]}


@router.post("/admin/products/unpublish")
def unpublish_products(data: PublishRequest, session: Session = Depends(get_session)):
    """Admin — unpublish one product, a batch, or an entire collection."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    query = select(Product)
    if data.product_ids:
        query = query.where(Product.id.in_(data.product_ids))
    elif data.category:
        query = query.where(Product.category == data.category)
    else:
        raise HTTPException(status_code=400, detail="Provide product_ids or category")

    products = session.exec(query).all()
    for p in products:
        p.is_published = False
        session.add(p)
    session.commit()
    return {"unpublished": len(products), "ids": [p.id for p in products]}


@router.get("/admin/catalog")
def get_catalog(master_key: str, session: Session = Depends(get_session)):
    """
    Admin — returns ALL products grouped by collection, split into
    published / unpublished. Used by the admin staging panel.
    Each product includes stock status for the badge.
    """
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    collections = [
        "Rings", "Necklaces", "Bracelets", "Earrings", "Anklets", "Ear Cuffs"
    ]

    # Only Silverbene products — excludes old soft-deleted products from before Silverbene
    all_products = session.exec(
        select(Product).where(Product.supplier_name == "Silverbene")
    ).all()

    catalog = {}
    for col in collections:
        col_products = [p for p in all_products if p.category == col]

        def card(p):
            return {
                "id": p.id,
                "name": p.name,
                "image_url": p.content_image_url or p.image_url,
                "final_price": p.final_price,
                "stock": p.stock,
                "in_stock": p.stock > 0,
                "is_published": p.is_published,
                "is_active": p.is_active,
                "category": p.category,
                "stock_auto_unpublished": getattr(p, "stock_auto_unpublished", False),
                "sync_miss_count": getattr(p, "sync_miss_count", 0),
            }

        def is_discontinued(p):
            return getattr(p, "sync_miss_count", 0) >= 1

        catalog[col] = {
            "published":     [card(p) for p in col_products if p.is_published is not False and p.stock > 0 and not is_discontinued(p)],
            "unpublished":   [card(p) for p in col_products if p.is_published is False and p.stock > 0 and not is_discontinued(p)],
            "out_of_stock":  [card(p) for p in col_products if p.stock == 0 and not is_discontinued(p)],
            "discontinued":  [card(p) for p in col_products if is_discontinued(p)],
        }

    total             = len(all_products)
    published_count   = sum(1 for p in all_products if p.is_published and p.stock > 0 and not getattr(p, "sync_miss_count", 0))
    unpublished_count = sum(1 for p in all_products if not p.is_published and p.stock > 0 and not getattr(p, "sync_miss_count", 0))
    oos_count         = sum(1 for p in all_products if p.stock == 0 and not getattr(p, "sync_miss_count", 0))
    disc_count        = sum(1 for p in all_products if getattr(p, "sync_miss_count", 0) >= 1)

    return {
        "summary": {
            "total":        total,
            "published":    published_count,
            "staged":       unpublished_count,
            "out_of_stock": oos_count,
            "discontinued": disc_count,
        },
        "collections": catalog,
    }


class ImageUpdateRequest(BaseModel):
    images: List[str]


@router.get("/admin/products/{product_id}/images")
def get_product_images(product_id: int, session: Session = Depends(get_session)):
    """Admin — return current image array for a product."""
    import json
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    images = json.loads(product.images or "[]")
    return {
        "product_id": product_id,
        "name": product.name,
        "images": images,
        "image_url": product.image_url,
        "content_image_url": product.content_image_url,
    }


@router.put("/admin/products/{product_id}/images")
def update_product_images(product_id: int, data: ImageUpdateRequest, session: Session = Depends(get_session)):
    """Admin — overwrite the images array for a product (after manual curation)."""
    import json
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.images = json.dumps(data.images)
    if data.images and not product.content_image_url:
        product.image_url = data.images[0]
    session.add(product)
    session.commit()
    return {"saved": len(data.images), "images": data.images}


@router.post("/admin/products/{product_id}/images/refresh")
def refresh_product_images(product_id: int, session: Session = Depends(get_session)):
    """Admin — re-fetch the full gallery from Silverbene for review."""
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    supplier_sku = product.cj_product_id
    if not supplier_sku:
        raise HTTPException(status_code=400, detail="No Silverbene SKU stored for this product")
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    sb = SilverbeneAdapter()
    raw = sb.get_by_sku(supplier_sku)
    if not raw:
        raise HTTPException(status_code=404, detail="Product not found at Silverbene — may be discontinued")
    gallery = raw.get("gallery", [])
    return {"images": gallery, "count": len(gallery)}


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