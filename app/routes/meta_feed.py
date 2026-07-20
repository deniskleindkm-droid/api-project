from fastapi import APIRouter
from fastapi.responses import Response
from sqlmodel import Session, select, or_
from app.database import engine
from app.models.product import Product
import json
import re
import xml.etree.ElementTree as ET

router = APIRouter(prefix="/feed")

_STORE = "https://mikisi.co"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _published_active(session: Session):
    return session.exec(
        select(Product).where(
            Product.is_active == True,
            Product.is_published == True,
            Product.image_url.is_not(None),
        )
    ).all()


def _additional_images(p: Product) -> list:
    # Prefer the Cloudinary-cached gallery over raw Silverbene URLs — a broken
    # image fetch here risks Meta flagging/disapproving the whole catalog
    # item, not just a failed Instagram post (see content_images' docstring
    # in models/product.py). Falls back to raw images for products not yet
    # backfilled (see image_cdn_agent.py's backfill_product_galleries).
    try:
        gallery_source = p.content_images or p.images
        gallery = json.loads(gallery_source) if gallery_source else []
    except Exception:
        gallery = []
    # Meta allows up to 10 additional_image_link entries — exclude the
    # primary image_link and dedupe while preserving order, so the shop's
    # product card shows real distinct photos instead of repeating the
    # single primary image.
    primary = p.content_image_url or p.image_url
    seen = {primary}
    extras = []
    for url in gallery:
        if url and url not in seen:
            seen.add(url)
            extras.append(url)
    return extras[:10]


def _description_with_size_note(p: Product) -> str:
    desc = _strip_html(p.description)
    try:
        from app.agents.suppliers.silverbene_adapter import sizes_are_variant_backed
        # sizes_are_variant_backed==False means p.sizes is real, useful info
        # (e.g. "Adjustable 16\"-18\"") that was never a distinct priced
        # choice — never a chip, per the site's own rule (see that
        # function's docstring), but it was reaching the feed nowhere at
        # all: not as a size (correctly excluded) and not anywhere else
        # either, so Instagram customers never saw it. Fold it into the
        # description text instead, same info the site shows as a badge.
        if not sizes_are_variant_backed(p.variants):
            sizes = json.loads(p.sizes) if p.sizes else []
            if sizes and sizes[0]:
                desc = f"{desc} {sizes[0]}.".strip()
    except Exception:
        pass
    return desc


def _base_fields(p: Product) -> dict:
    extras = _additional_images(p)
    return {
        "title": p.name,
        "description": _description_with_size_note(p),
        "condition": "new",
        "link": f"{_STORE}/products/{p.id}",
        "image_link": p.content_image_url or p.image_url,
        "additional_image_link": extras,
        "brand": "Mikisi",
        "google_product_category": "188",
        "product_type": p.category,
        "material": p.material or None,
    }


def _items_for(p: Product, session: Session) -> list:
    """
    One feed row per product, UNLESS the product has 2+ real priced
    variants (different size/color options with their own price) — Meta's
    own docs flag "no unique Product IDs for each product variant" as a
    cause of broken/empty native-checkout carts. Reuses
    products.get_variant_prices() rather than re-deriving size/color/price
    here, since that resolution (Silverbene attribute parsing, purity vs
    color, bracelet/necklace size units, etc.) is intricate and must never
    disagree with what the product page itself shows — see that function's
    own comments. Falls back to a single legacy row (retailer_id ==
    product.id, no item_group_id) when there's nothing real to split on,
    which also preserves the retailer_id every currently-approved catalog
    product already uses.
    """
    base = _base_fields(p)

    try:
        from app.routes.products import get_variant_prices
        variants = get_variant_prices(p.id, None, session)
    except Exception:
        variants = []

    if len(variants) < 2:
        # A product with exactly ONE priced variant still has real
        # color/size data worth sending (e.g. a single adjustable-length
        # necklace option) — found live tonight: this branch hardcoded
        # color/size to None regardless, silently dropping a genuinely
        # real size (product 721 has one variant whose size correctly
        # resolves to "Adjustable 16\"-18\"" via get_variant_prices, but
        # the feed showed nothing at all because it never reached here).
        # Only truly variant-less products (empty list) get None/None.
        v = variants[0] if variants else None
        # available defaults True when absent (variant never flagged by the stock
        # sync's per-variant existence check — see _reconcile_variant_availability
        # in silverbene_stock_agent.py). False means Silverbene confirmed this
        # specific option no longer exists there — send it as out of stock rather
        # than dropping the row, so it stays a real (if unselectable) catalog item.
        v_available = (v.get("available", True) if v else True)
        return [{
            **base,
            "id": str(p.id),
            "item_group_id": None,
            "availability": "in stock" if v_available and (v["stock"] if v else p.stock) > 0 else "out of stock",
            "price": f"{(v['final_price'] if v else p.final_price):.2f} USD",
            "color": v.get("color") if v else None,
            "size": v.get("size") if v else None,
        }]

    items = []
    for v in variants:
        option_id = v.get("option_id")
        if option_id is None:
            continue
        v_available = v.get("available", True)
        # Prefer the internal ProductVariant id (Mikisi's own, supplier-
        # independent) for the public catalog identity and deep link once a
        # product has been backfilled into that table — decouples the
        # storefront's public IDs from Silverbene's own numbering, so
        # re-sourcing a product from a different supplier later never breaks
        # an already-approved Meta catalog entry or an already-tagged
        # Instagram post. Falls back to the legacy option_id-based scheme for
        # any product not yet backfilled (see [[refactored-wobbling-rabin]]) —
        # get_variant_prices() returns `id: null` for those, never `id: p.id-None`.
        variant_id = v.get("id")
        catalog_id = f"{p.id}-{variant_id}" if variant_id is not None else f"{p.id}-{option_id}"
        deep_link_param = f"variant_id={variant_id}" if variant_id is not None else f"option_id={option_id}"
        items.append({
            **base,
            "id": catalog_id,
            "item_group_id": str(p.id),
            "link": f"{_STORE}/products/{p.id}?{deep_link_param}",
            "availability": "in stock" if v_available and (v.get("stock") or 0) > 0 else "out of stock",
            "price": f"{v['final_price']:.2f} USD",
            "color": v.get("color"),
            "size": v.get("size"),
        })
    return items or [{
        **base,
        "id": str(p.id),
        "item_group_id": None,
        "availability": "in stock" if p.stock > 0 else "out of stock",
        "price": f"{p.final_price:.2f} USD",
        "color": None,
        "size": None,
    }]


@router.get("/meta-products")
def meta_products_json():
    with Session(engine) as session:
        products = _published_active(session)
        data = [item for p in products for item in _items_for(p, session)]
    return {"data": data}


@router.get("/meta-products.xml")
def meta_products_xml():
    with Session(engine) as session:
        products = _published_active(session)
        rows = [item for p in products for item in _items_for(p, session)]

    rss = ET.Element("rss", {"xmlns:g": "http://base.google.com/ns/1.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Mikisi Jewelry"
    ET.SubElement(channel, "link").text = _STORE
    ET.SubElement(channel, "description").text = "Luxury 925 Sterling Silver Jewelry"

    for d in rows:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "g:id").text = d["id"]
        if d["item_group_id"]:
            ET.SubElement(item, "g:item_group_id").text = d["item_group_id"]
        ET.SubElement(item, "g:title").text = d["title"]
        ET.SubElement(item, "g:description").text = d["description"]
        ET.SubElement(item, "g:availability").text = d["availability"]
        ET.SubElement(item, "g:condition").text = d["condition"]
        ET.SubElement(item, "g:price").text = d["price"]
        ET.SubElement(item, "g:link").text = d["link"]
        ET.SubElement(item, "g:image_link").text = d["image_link"]
        for extra_url in d["additional_image_link"]:
            ET.SubElement(item, "g:additional_image_link").text = extra_url
        if d["color"]:
            ET.SubElement(item, "g:color").text = d["color"]
        if d["size"]:
            ET.SubElement(item, "g:size").text = d["size"]
        if d["material"]:
            ET.SubElement(item, "g:material").text = d["material"]
        ET.SubElement(item, "g:brand").text = d["brand"]
        ET.SubElement(item, "g:google_product_category").text = d["google_product_category"]
        ET.SubElement(item, "g:product_type").text = d["product_type"]

    body = '<?xml version="1.0"?>\n' + ET.tostring(rss, encoding="unicode")
    return Response(content=body, media_type="application/xml")
