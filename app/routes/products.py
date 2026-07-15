from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import Session, select
from app.models.product import Product, ProductCreate, ProductPublic
from app.database import get_session
from typing import Optional, List
from pydantic import BaseModel
import json as _json
import re as _re

router = APIRouter()


# ── Size display metadata ──────────────────────────────────────────────────────

_SIZE_LABELS = {
    "Bracelets": "Bracelet Length",
    "Necklaces": "Chain Length",
    "Rings":     "Ring Size",
    "Anklets":   "Anklet Length",
    "Earrings":  "Size",
    "Ear Cuffs": "Size",
}

_SIZE_HINTS = {
    "Bracelets": 'Measure your wrist and add ½” for a standard fit. When between sizes, size up.',
    "Necklaces": '16” rests at the base of the neck · 18” at the collarbone · 20” at the chest · 22” near the heart',
    "Rings":     'Wrap a paper strip around your finger, mark where it meets, and measure that length in mm. Divide by 3.14 to find your inner diameter.',
    "Anklets":   'Measure your ankle and add ½” for a relaxed fit.',
}


def _size_display_meta(p) -> dict:
    category = p.category or ""
    try:
        _s = _json.loads(p.sizes or "[]")
        if isinstance(_s, str):
            _s = _json.loads(_s)
        sizes = _s if isinstance(_s, list) else []
    except Exception:
        sizes = []

    label = _SIZE_LABELS.get(category)
    # Most earring/ear cuff sizes are hoop diameters — use the specific label
    # the customer actually understands. Studs/tubes/other shapes keep the
    # generic "Size" default since a diameter-style label wouldn't fit them.
    if category in ("Earrings", "Ear Cuffs") and "hoop" in (p.name or "").lower():
        label = "Hoop Size"

    # Rings with no size data at all are just as open/adjustable as rings whose
    # sizes explicitly say so — Silverbene simply omits the Size attribute when
    # there's nothing to select. Treat both the same way instead of falling
    # through to "none" and hiding the ring size section entirely.
    if category == "Rings" and not sizes:
        from app.agents.suppliers.silverbene_adapter import open_ring_size_text
        try:
            specs = _json.loads(p.specs or "{}")
        except Exception:
            specs = {}
        badge = open_ring_size_text(specs)
        return {"size_label": label, "size_hint": badge, "size_display_mode": "open_badge"}

    # Bangles are sized by inner diameter, not wrist length — a rigid band's
    # diameter and a chain's wrist circumference are different measurements
    # (see silverbene_adapter._extract_bracelet_info_from_desc), so bangles
    # never get a "Bracelet Length" selector. Surface the real diameter as its
    # own badge instead of silently hiding the size section.
    if category == "Bracelets" and not sizes:
        try:
            specs = _json.loads(p.specs or "{}")
        except Exception:
            specs = {}
        inner_diameter = specs.get("inner_diameter")
        if inner_diameter:
            return {"size_label": "Inner Diameter", "size_hint": inner_diameter, "size_display_mode": "open_badge"}

    # Most earrings/ear cuffs are sold as a fixed pair with no real size choice —
    # only show a selector for the minority that do have genuine, price-backed
    # size options (e.g. hoop diameter, stud size).
    if not sizes:
        return {"size_label": label, "size_hint": None, "size_display_mode": "none"}

    sizes_lower = [s.lower() for s in sizes]

    if category == "Rings" and any("open" in s for s in sizes_lower):
        from app.agents.suppliers.silverbene_adapter import open_ring_size_text
        try:
            specs = _json.loads(p.specs or "{}")
        except Exception:
            specs = {}
        badge = open_ring_size_text(specs)
        return {"size_label": label, "size_hint": badge, "size_display_mode": "open_badge"}

    # A chip like "Adjustable 6.5\" – 7\"" carries a real measurement even
    # though the word "adjustable" appears in it — only treat the whole set
    # as a vague label when none of them contain an actual digit.
    _has_digit = any(_re.search(r'\d', s) for s in sizes)
    if not _has_digit and all(
        "adjustable" in s or "one size" in s or "open size" in s or s == "free size"
        for s in sizes_lower
    ):
        return {"size_label": label, "size_hint": None, "size_display_mode": "adjustable_badge"}

    return {
        "size_label":        label,
        "size_hint":         _SIZE_HINTS.get(category),
        "size_display_mode": "selector",
    }


def _to_public(p) -> ProductPublic:
    pub_keys = set(ProductPublic.model_fields) - {"size_label", "size_hint", "size_display_mode"}
    data = {k: getattr(p, k, None) for k in pub_keys}
    data.update(_size_display_meta(p))
    return ProductPublic(**data)


# ── HERO BANNER ───────────────────────────────────────────────────────────────

class HeroUpdate(BaseModel):
    banner_url: Optional[str] = None    # direct URL (CDN, Cloudinary, etc.)
    banner_b64: Optional[str] = None    # base64 encoded image for direct upload
    tagline: Optional[str] = None
    master_key: str

@router.get("/store/hero")
def get_hero():
    """
    Public — returns hero banner image, video, tagline, and the rotating hero
    image set for the storefront. `rotation` (real product photos, hand-picked
    and stored via hero_rotation config) takes priority on the frontend when
    present; banner_url/video_url remain as a fallback for when the rotation
    hasn't been populated yet.
    """
    from app.agents.store_config import get_config
    try:
        rotation = _json.loads(get_config("hero_rotation", default="[]") or "[]")
    except Exception:
        rotation = []
    return {
        "banner_url": get_config("hero_banner_url", default="") or None,
        "video_url":  get_config("hero_video_url",  default="") or None,
        "tagline":    get_config("hero_tagline", default="Unique pieces you won't find everywhere — genuine 925 sterling silver, honest prices, always something new."),
        "rotation":   rotation,
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

    from app.agents.store_config import get_hidden_categories
    hidden = get_hidden_categories()
    if hidden:
        query = query.where(Product.category.notin_(hidden))

    if brand:
        query = query.where(Product.brand == brand)
    if category:
        query = query.where(Product.category == category)
    if min_price:
        query = query.where(Product.final_price >= min_price)
    if max_price:
        query = query.where(Product.final_price <= max_price)

    products = session.exec(query).all()
    return [_to_public(p) for p in products]

@router.get("/products/{product_id}", response_model=ProductPublic)
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _to_public(product)


@router.get("/products/{product_id}/variant-prices")
def get_variant_prices(product_id: int, session: Session = Depends(get_session)):
    """
    Return per-variant pricing for a product.
    Used by the frontend to update the displayed price when a customer
    selects a size or color.

    Response: list of {option_id, size, color, final_price, stock}
    Only includes variants with a known base_price.
    """
    import re as _re
    import json as _json
    from app.agents.jewelry_pricing import calculate_mikisi_price
    from app.agents.suppliers.silverbene_adapter import (
        _normalize_size_for_match, _normalize_color_final,
        _clean_color_value, _split_color_and_size,
        _clean_compound_color, _clean_plain_color, _is_compound_color_candidate,
        _detect_option_suffix,
        COLOR_ATTRIBUTE_NAMES, BRACELET_SIZE_ATTR_NAMES,
        parse_necklace_length, parse_bracelet_size,
    )

    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    try:
        variants = _json.loads(product.variants or "[]")
    except Exception:
        return []

    from app.agents.suppliers.silverbene_adapter import _bracelet_size_denom
    _denom = _bracelet_size_denom(variants)

    # Mirrors _extract_variants()'s _purity_is_real pre-scan — "Purity" is
    # boilerplate material text ("925 Sterling Silver") on most products,
    # identical across every option, and only a real second selector when it
    # actually varies (e.g. "18k gold" vs "No plating"). Must agree with
    # p.colors or this endpoint's color field would disagree with what the
    # customer sees in the chip.
    _purity_vals_seen = set()
    for _v in variants:
        for _a in (_v.get("attribute") or _v.get("attributes") or []):
            if (_a.get("name") or "").lower().strip() != "purity":
                continue
            _pval = (_a.get("value") or "").strip()
            if _pval and _re.search(r'\b(gold|silver|platinum|plating|plated|rhodium)\b', _pval, _re.I):
                _norm = _normalize_color_final(_clean_plain_color(_pval), "finish", normalize_rhodium=False)
                if _norm:
                    _purity_vals_seen.add(_norm)
    _purity_is_real = len(_purity_vals_seen) > 1

    result = []
    for v in variants:
        bp = v.get("base_price") or v.get("price")
        if not bp:
            continue
        bp = float(bp)
        final_price = calculate_mikisi_price(bp)["final_price"]

        attrs = v.get("attribute") or v.get("attributes") or []
        size = None
        _chain_suffix = _detect_option_suffix(attrs)
        _color_parts = []
        for a in attrs:
            name = (a.get("name") or "").lower().strip()
            val  = (a.get("value") or "").strip()
            if name in BRACELET_SIZE_ATTR_NAMES:
                chips = parse_bracelet_size(val, _denom)
                size = chips[0] if chips else val
            elif name in ("size", "ring size", "bracelet size", "anklet size"):
                size = _normalize_size_for_match(val)
                # A raw "15cm"/"16Cm" value has no US/Size/No. prefix, so
                # _normalize_size_for_match() returns it unchanged (truthy) —
                # never skip the mm/cm→inch conversion just because that
                # returned something. Mirrors attr_size() in
                # resolve_option_id(), which this endpoint must always agree
                # with (same size chip shown in the selector must resolve to
                # the same variant here for the price to actually update).
                if val and _re.search(r'\d+\s*(mm|cm)', val, _re.I):
                    chips = parse_bracelet_size(val, _denom) or parse_necklace_length(val)
                    if chips:
                        size = chips[0]
            elif name in ("chain length", "length") and val:
                chips = parse_bracelet_size(val, _denom) or parse_necklace_length(val)
                if chips:
                    size = chips[0]
            elif name in COLOR_ATTRIBUTE_NAMES and val:
                if _re.search(r'\d+\s*(mm|cm)', val, _re.I):
                    # Measurement bundled into the Color attr (hoop diameter, tube
                    # width, bracelet extension) — split it the same way
                    # _extract_variants() does so size/color here always agree
                    # with what p.sizes/p.colors and the frontend chips show.
                    color_part, size_chip = _split_color_and_size(val)
                    part = _normalize_color_final(color_part, name)
                    if size_chip and not size:
                        size = size_chip
                elif _is_compound_color_candidate(val):
                    # Comma-compound with no measurement (metal + stone color, metal +
                    # grade, etc.) — combine into one unique chip the same way
                    # _extract_variants() does, so this always agrees with p.colors.
                    part = _clean_compound_color(val)
                else:
                    # Use the same fully-normalized value that p.colors stores —
                    # _normalize_color_final turns "Rhodium"→"Silver", "Pink"→"Rose Gold", etc.
                    # An exact category word ("Anklet","Necklace") normally cleans to ""
                    # as noise, but _extract_variants() rescues it as the real color
                    # when it's the only thing that varies — fall back to the raw word
                    # so this endpoint stays consistent with p.colors in that case.
                    part = _normalize_color_final(_clean_plain_color(val), name) or val
                if part:
                    _color_parts.append(part)
            elif name == "purity" and _purity_is_real and val and _re.search(r'\b(gold|silver|platinum|plating|plated|rhodium)\b', val, _re.I):
                # Mirrors _extract_variants()'s "purity" branch — Silverbene
                # sometimes uses "Purity" for the plating/finish choice
                # instead of "Color" (e.g. "18k gold" vs "No plating"). Only
                # fires on a metal/plating-shaped value so it never collides
                # with _detect_option_suffix's pendant/chain-style reading of
                # the same attribute name.
                part = _normalize_color_final(_clean_plain_color(val), "finish", normalize_rhodium=False)
                if part:
                    _color_parts.append(part)
        # Combine every real color-type attribute this option carries (e.g. a
        # separate metal "Color" + gem "Main Stone") into ONE chip, mirroring
        # _extract_variants() so this endpoint always agrees with p.colors. A
        # suffix only ever means anything attached to a real color — see
        # _extract_variants() for why a bare suffix must never stand in alone.
        color = ' · '.join(_color_parts)
        if _chain_suffix and color:
            color = f'{color} · {_chain_suffix}'
        color = color or None

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
        p.is_reviewed = True  # a deliberate decision was just made — no longer "New"
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
        p.is_reviewed = True  # a deliberate decision was just made — no longer "New"
        session.add(p)
    session.commit()
    return {"unpublished": len(products), "ids": [p.id for p in products]}


class HiddenCategoriesUpdate(BaseModel):
    master_key: str
    categories: List[str]


@router.get("/admin/hidden-categories")
def get_hidden_categories_admin(master_key: str):
    """Admin — categories currently disconnected from every customer-facing listing."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    from app.agents.store_config import get_hidden_categories
    return {"hidden_categories": sorted(get_hidden_categories())}


@router.put("/admin/hidden-categories")
def set_hidden_categories_admin(data: HiddenCategoriesUpdate):
    """
    Admin — set the full list of categories hidden from /products,
    /collections, /collections/{id}/products, and Instagram posting.
    Products themselves are untouched (still is_published as before) —
    this only disconnects the category from customer-facing discovery, so
    it can be reviewed slowly and re-enabled later with no code change.
    """
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    from app.agents.store_config import set_hidden_categories
    set_hidden_categories(data.categories)
    return {"hidden_categories": data.categories}


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
                "is_reviewed": getattr(p, "is_reviewed", False),
                "is_active": p.is_active,
                "category": p.category,
                "stock_auto_unpublished": getattr(p, "stock_auto_unpublished", False),
                "sync_miss_count": getattr(p, "sync_miss_count", 0),
            }

        def is_discontinued(p):
            return getattr(p, "sync_miss_count", 0) >= 1

        def is_new(p):
            # Fresh import, no publish/unpublish decision made yet — distinct from
            # "Unpublished / Staged", which means Dennis looked at it and deliberately
            # held it back. Publishing OR unpublishing a product marks it reviewed.
            return p.is_published is False and not getattr(p, "is_reviewed", False)

        catalog[col] = {
            "new":           [card(p) for p in col_products if is_new(p) and p.stock > 0 and not is_discontinued(p)],
            "published":     [card(p) for p in col_products if p.is_published is not False and p.stock > 0 and not is_discontinued(p)],
            "unpublished":   [card(p) for p in col_products if p.is_published is False and not is_new(p) and p.stock > 0 and not is_discontinued(p)],
            "out_of_stock":  [card(p) for p in col_products if p.stock == 0 and not is_discontinued(p)],
            "discontinued":  [card(p) for p in col_products if is_discontinued(p)],
        }

    total             = len(all_products)
    published_count   = sum(1 for p in all_products if p.is_published and p.stock > 0 and not getattr(p, "sync_miss_count", 0))
    new_count         = sum(1 for p in all_products if p.is_published is False and not getattr(p, "is_reviewed", False) and p.stock > 0 and not getattr(p, "sync_miss_count", 0))
    unpublished_count = sum(1 for p in all_products if not p.is_published and getattr(p, "is_reviewed", False) and p.stock > 0 and not getattr(p, "sync_miss_count", 0))
    oos_count         = sum(1 for p in all_products if p.stock == 0 and not getattr(p, "sync_miss_count", 0))
    disc_count        = sum(1 for p in all_products if getattr(p, "sync_miss_count", 0) >= 1)

    return {
        "summary": {
            "total":        total,
            "new":          new_count,
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