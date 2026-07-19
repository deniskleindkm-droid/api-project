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
    try:
        gallery = json.loads(p.images) if p.images else []
    except Exception:
        gallery = []
    # Meta allows up to 10 additional_image_link entries — exclude the
    # primary image_link (product.image_url) and dedupe while preserving
    # order, so the shop's product card shows real distinct photos
    # instead of repeating the single primary image.
    seen = {p.image_url}
    extras = []
    for url in gallery:
        if url and url not in seen:
            seen.add(url)
            extras.append(url)
    return extras[:10]


def _base_fields(p: Product) -> dict:
    extras = _additional_images(p)
    return {
        "title": p.name,
        "description": _strip_html(p.description),
        "condition": "new",
        "link": f"{_STORE}/products/{p.id}",
        "image_link": p.image_url,
        "additional_image_link": extras,
        "brand": "Mikisi",
        "google_product_category": "188",
        "product_type": p.category,
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
        return [{
            **base,
            "id": str(p.id),
            "item_group_id": None,
            "availability": "in stock" if p.stock > 0 else "out of stock",
            "price": f"{p.final_price:.2f} USD",
            "color": None,
            "size": None,
        }]

    items = []
    for v in variants:
        option_id = v.get("option_id")
        if option_id is None:
            continue
        items.append({
            **base,
            "id": f"{p.id}-{option_id}",
            "item_group_id": str(p.id),
            "link": f"{_STORE}/products/{p.id}?option_id={option_id}",
            "availability": "in stock" if (v.get("stock") or 0) > 0 else "out of stock",
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
        ET.SubElement(item, "g:brand").text = d["brand"]
        ET.SubElement(item, "g:google_product_category").text = d["google_product_category"]
        ET.SubElement(item, "g:product_type").text = d["product_type"]

    body = '<?xml version="1.0"?>\n' + ET.tostring(rss, encoding="unicode")
    return Response(content=body, media_type="application/xml")
