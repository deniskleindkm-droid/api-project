"""
Specs Backfill Agent
--------------------
Finds active Silverbene products with no specs data, re-fetches their
raw description from the Silverbene API, and populates the specs field.

Runs on startup and every 24 hours. Stops silently once all products
have specs. Safe to re-run — skips products that already have specs.
"""
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product
import json


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

    updated = 0
    skipped = 0

    for p in products:
        try:
            raw = sb.get_by_sku(p.cj_product_id)
            if not raw:
                skipped += 1
                continue

            # get_by_sku returns the processed dict — raw HTML desc is under 'description' key
            desc = raw.get("description", "")
            specs = sb._extract_specs_from_desc(desc)

            with Session(engine) as session:
                product = session.get(Product, p.id)
                if product:
                    # Store real specs if found; store '{}' if none found so this
                    # product isn't re-fetched on every future run
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
