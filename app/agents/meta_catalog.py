"""
Meta (Facebook/Instagram) Commerce Catalog lookup.
----------------------------------------------------
Resolves a Mikisi product to its Meta catalog product ID so
instagram_agent.py can tag it in a post (the shopping-bag icon that links
straight to the product from inside Instagram, in addition to the caption
link that already works today).

Requires FACEBOOK_CATALOG_ID and a token with catalog read access.
FACEBOOK_CATALOG_TOKEN (a dedicated system-user token scoped to catalog
access, added 2026-07-17) is preferred — falls back to
FACEBOOK_ACCESS_TOKEN (the Page token, used for posting) only if the
catalog-specific one isn't set, since a Page token doesn't necessarily
carry catalog_management permission. Every caller degrades gracefully to
"no tag" if nothing usable is configured or the lookup fails — a
missing/failed tag must never block the post itself, since the caption's
direct product link already works without this.

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
    per product, not on every post — EXCEPT for multi-variant products
    (see app/routes/meta_feed.py), which are always re-checked fresh.

    Why: multi-variant products are split into per-variant catalog entries
    under item_group_id == product_id, with no plain retailer_id ==
    product_id entry at all. A cache populated before a product
    transitioned into that split structure would be permanently stale —
    found live 2026-07-18, where a cached flat-product ID kept being
    returned after the split replaced it, silently breaking every tag
    attempt with no error anywhere pointing at the cache being the cause.
    """
    catalog_id = os.getenv("FACEBOOK_CATALOG_ID")
    access_token = os.getenv("FACEBOOK_CATALOG_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN")
    if not catalog_id or not access_token:
        return ""

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return ""
        from app.routes.products import get_variant_prices
        try:
            is_split = len(get_variant_prices(product_id, None, session)) >= 2
        except Exception:
            is_split = False
        if product.meta_catalog_product_id and not is_split:
            return product.meta_catalog_product_id

    try:
        items = []
        if not is_split:
            r = requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{catalog_id}/products",
                params={
                    "filter": f'{{"retailer_id":{{"eq":"{product_id}"}}}}',
                    "fields": "id,retailer_id,name",
                    "access_token": access_token,
                },
                timeout=15,
            )
            items = r.json().get("data", [])

        if not items:
            # Multi-variant products use "{product_id}-{variant_id}" retailer_ids
            # (the internal ProductVariant id — Silverbene's own option_id for
            # any product not yet backfilled, see meta_feed.py's _items_for())
            # instead of a plain retailer_id match. Note: item_group_id is NOT
            # a valid filterable/readable field on this endpoint (confirmed
            # live — Meta returns "Invalid field names: item_group_id")
            # despite being a real field on the feed side, so match on the
            # retailer_id prefix instead — unaffected by which id scheme the
            # suffix uses, since only the "{product_id}-" prefix is matched.
            r = requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{catalog_id}/products",
                params={
                    "filter": f'{{"retailer_id":{{"i_contains":"{product_id}-"}}}}',
                    "fields": "id,retailer_id,name",
                    "access_token": access_token,
                },
                timeout=15,
            )
            items = r.json().get("data", [])

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
