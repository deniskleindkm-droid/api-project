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
    Extract specs from the raw Silverbene item dict.
    Tries multiple fields since Silverbene stores specs in different places:
      - raw['desc']       → HTML description with <li> spec tags
      - raw['attribute']  → list of {name, value} pairs (product attributes)
      - raw['spec']       → may exist on some products
    """
    specs = {}

    # Primary: parse raw HTML desc field (before any AI rewrite)
    desc = raw.get("desc", "")
    if desc:
        specs.update(sb._extract_specs_from_desc(desc))

    # Secondary: attribute list — [{name: "Stone Type", value: "Cubic Zirconia"}, ...]
    attr_map = {
        "stone type": "stone", "main stone": "stone", "stone name": "stone",
        "accent stone": "accent_stone",
        "stone color": "stone",
        "bead shape": "bead_shape", "bead type": "bead_shape",
        "setting": "setting", "setting type": "setting",
        "closure": "closure", "clasp": "closure",
        "finish": "finish", "surface": "finish",
        "color": "color", "color combination": "color",
        "total weight": "weight", "weight": "weight",
        "ring width": "width", "band width": "width", "chain width": "width",
        "ring top size": "ring_top",
        "purity": "purity",
    }
    for attr in raw.get("attribute", []):
        if not isinstance(attr, dict):
            continue
        key = (attr.get("name") or attr.get("key") or "").strip().lower()
        val = (attr.get("value") or "").strip()
        if key and val and key in attr_map:
            field = attr_map[key]
            if field not in specs:  # don't overwrite desc-parsed values
                specs[field] = val

    # Also try 'spec' field if present
    for attr in raw.get("spec", []):
        if not isinstance(attr, dict):
            continue
        key = (attr.get("name") or attr.get("key") or "").strip().lower()
        val = (attr.get("value") or "").strip()
        if key and val and key in attr_map:
            field = attr_map[key]
            if field not in specs:
                specs[field] = val

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
            known_fields = [k for k in first_raw.keys() if k not in ('gallery',)]
            print(f"[Specs Backfill] Raw API fields available: {known_fields}")
            for field in ('desc', 'attribute', 'spec', 'specification'):
                val = first_raw.get(field)
                if val:
                    preview = str(val)[:200]
                    print(f"[Specs Backfill]   {field}: {preview}")
        else:
            print(f"[Specs Backfill] WARNING: get_by_sku returned nothing for first product "
                  f"({products[0].cj_product_id}) — API may not support SKU lookup")

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
