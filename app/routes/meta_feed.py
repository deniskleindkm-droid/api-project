from fastapi import APIRouter
from fastapi.responses import Response
from sqlmodel import Session, select, or_
from app.database import engine
from app.models.product import Product
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


def _item(p: Product) -> dict:
    return {
        "id": str(p.id),
        "title": p.name,
        "description": _strip_html(p.description),
        "availability": "in stock" if p.stock > 0 else "out of stock",
        "condition": "new",
        "price": f"{p.final_price:.2f} USD",
        "link": f"{_STORE}/products/{p.id}",
        "image_link": p.image_url,
        "brand": "Mikisi",
        "google_product_category": "188",
        "product_type": p.category,
    }


@router.get("/meta-products")
def meta_products_json():
    with Session(engine) as session:
        products = _published_active(session)
    return {"data": [_item(p) for p in products]}


@router.get("/meta-products.xml")
def meta_products_xml():
    with Session(engine) as session:
        products = _published_active(session)

    rss = ET.Element("rss", {"xmlns:g": "http://base.google.com/ns/1.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Mikisi Jewelry"
    ET.SubElement(channel, "link").text = _STORE
    ET.SubElement(channel, "description").text = "Luxury 925 Sterling Silver Jewelry"

    for p in products:
        d = _item(p)
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "g:id").text = d["id"]
        ET.SubElement(item, "g:title").text = d["title"]
        ET.SubElement(item, "g:description").text = d["description"]
        ET.SubElement(item, "g:availability").text = d["availability"]
        ET.SubElement(item, "g:condition").text = d["condition"]
        ET.SubElement(item, "g:price").text = d["price"]
        ET.SubElement(item, "g:link").text = d["link"]
        ET.SubElement(item, "g:image_link").text = d["image_link"]
        ET.SubElement(item, "g:brand").text = d["brand"]
        ET.SubElement(item, "g:google_product_category").text = d["google_product_category"]
        ET.SubElement(item, "g:product_type").text = d["product_type"]

    body = '<?xml version="1.0"?>\n' + ET.tostring(rss, encoding="unicode")
    return Response(content=body, media_type="application/xml")
