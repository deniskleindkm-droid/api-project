"""
Meta (Facebook/Instagram) Commerce Catalog lookup.
----------------------------------------------------
Resolves a Mikisi product to its Meta catalog product ID so
instagram_agent.py can tag it in a post (the shopping-bag icon that links
straight to the product from inside Instagram, in addition to the caption
link that already works today).

Requires FACEBOOK_CATALOG_ID and FACEBOOK_ACCESS_TOKEN — not yet
confirmed live on this deployment as of 2026-07-16 (see GET
/admin/instagram/env-check, which reports presence only, never values).
Every caller degrades gracefully to "no tag" if either is missing or the
lookup fails — a missing/failed tag must never block the post itself,
since the caption's direct product link already works without this.

Assumes the catalog's retailer_id field was populated with Mikisi's own
product.id when the feed was set up — verify this is actually true (see
/admin/instagram/meta-catalog-test) before trusting it in a real post,
rather than assuming the mapping matches just because it was described
that way.
"""
import os
import requests
from sqlmodel import Session
from app.database import engine
from app.models.product import Product

GRAPH_API_VERSION = "v18.0"


def resolve_meta_product_id(product_id: int) -> str:
    """
    Returns the Meta catalog product ID for this Mikisi product, or "" if
    unavailable (catalog not configured, product not found in the catalog,
    or the lookup failed). Caches a successful resolution on
    product.meta_catalog_product_id so this only hits the Graph API once
    per product, not on every post.
    """
    catalog_id = os.getenv("FACEBOOK_CATALOG_ID")
    access_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
    if not catalog_id or not access_token:
        return ""

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return ""
        if product.meta_catalog_product_id:
            return product.meta_catalog_product_id

    try:
        r = requests.get(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{catalog_id}/products",
            params={
                "filter": f'{{"retailer_id":{{"eq":"{product_id}"}}}}',
                "fields": "id,retailer_id,name",
                "access_token": access_token,
            },
            timeout=15,
        )
        data = r.json()
        items = data.get("data", [])
        if not items:
            print(f"[Meta Catalog] Product {product_id} not found in catalog {catalog_id} — posting without a tag")
            return ""

        meta_id = items[0]["id"]
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product:
                product.meta_catalog_product_id = meta_id
                session.add(product)
                session.commit()
        return meta_id

    except Exception as e:
        print(f"[Meta Catalog] Lookup failed for product {product_id}: {e}")
        return ""
