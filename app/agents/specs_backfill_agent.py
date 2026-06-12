"""
Specs Backfill Agent
--------------------
Finds active Silverbene products with no specs data, re-fetches their
raw API response directly (bypassing the processed dict), extracts specs
from whatever fields Silverbene uses, and stores them.

Runs on startup and every 24 hours. Stops silently once all products
have specs. Safe to re-run — skips products that already have specs.
"""
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product
import json


def _fetch_raw_silverbene(sb, sku: str) -> dict:
    """
    Fetch the raw Silverbene API response for a product SKU —
    bypasses _to_standard() so we get all original fields.
    """
    from app.agents.suppliers.silverbene_adapter import ENDPOINT_PRODUCT_LIST
    resp = sb._get(ENDPOINT_PRODUCT_LIST, {"sku": sku})
    if not isinstance(resp, dict) or resp.get("code") != 0:
        return {}
    data = resp.get("data", {})
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", [])
    else:
        items = []
    return items[0] if items else {}


def _extract_specs_from_raw(raw: dict, sb) -> dict:
    """
    Extract specs from the raw Silverbene product_list response.
    product_list uses 'description' (not 'desc') and has 'weight' as a direct field.
    """
    specs = {}

    # Weight is a direct top-level field in product_list (a number, in grams)
    weight = raw.get("weight")
    if weight is not None:
        try:
            w = float(weight)
            if w > 0:
                specs["weight"] = f"{w:g}g"
        except (TypeError, ValueError):
            pass

    # Parse the description HTML for spec <li> tags —
    # product_list calls it 'description'; product_by_date calls it 'desc'
    desc_html = raw.get("description") or raw.get("desc") or ""
    if desc_html:
        parsed = sb._extract_specs_from_desc(desc_html)
        # Don't overwrite weight we already got from the direct field
        for k, v in parsed.items():
            if k not in specs:
                specs[k] = v

    return specs


def run_specs_backfill():
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter

    sb = SilverbeneAdapter()

    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.supplier_name == "Silverbene",
                Product.specs == None,
                Product.cj_product_id != None,
            )
        ).all()

    if not products:
        print("[Specs Backfill] All products already have specs — nothing to do")
        return

    print(f"[Specs Backfill] {len(products)} products need specs — fetching from Silverbene")

    # Log the raw fields from the first product so we can see what Silverbene returns
    if products:
        first_raw = _fetch_raw_silverbene(sb, products[0].cj_product_id)
        if first_raw:
            print(f"[Specs Backfill] Raw API fields: {list(first_raw.keys())}")
            for field in ('description', 'desc', 'weight'):
                val = first_raw.get(field)
                if val is not None:
                    preview = str(val)[:300]
                    print(f"[Specs Backfill]   {field}: {preview}")
        else:
            print(f"[Specs Backfill] WARNING: raw fetch returned nothing for first product "
                  f"({products[0].cj_product_id})")

    updated = 0
    skipped = 0

    for p in products:
        try:
            raw = _fetch_raw_silverbene(sb, p.cj_product_id)
            if not raw:
                skipped += 1
                continue

            specs = _extract_specs_from_raw(raw, sb)

            with Session(engine) as session:
                product = session.get(Product, p.id)
                if product:
                    product.specs = json.dumps(specs) if specs else '{}'
                    session.add(product)
                    session.commit()
                    if specs:
                        updated += 1
                        print(f"[Specs Backfill] ✓ {p.name[:50]} → {list(specs.keys())}")
                    else:
                        skipped += 1

        except Exception as e:
            print(f"[Specs Backfill] Error on product {p.id} ({p.name[:40]}): {e}")
            skipped += 1

    print(f"[Specs Backfill] Done — updated={updated} skipped={skipped}")
