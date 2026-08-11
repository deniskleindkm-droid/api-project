"""
One-time backfill: writes style_tags/occasion into the real product table
from the already-researched and photo-audited tagging in the
docs/demo-collections*.html demo pages, matched by product id.

Run manually, per collection, once the demo's tagging is finalized:
    python scripts/backfill_style_occasion.py <demo_file> <category>
"""
import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from sqlmodel import Session
from app.database import engine
from app.models.product import Product


def backfill(demo_path: str, category: str):
    text = open(demo_path, encoding="utf-8").read()
    m = re.search(r"const PRODUCTS = (\[.*?\]);", text)
    demo_products = json.loads(m.group(1))

    updated = missing = 0
    with Session(engine) as session:
        for dp in demo_products:
            p = session.get(Product, dp["id"])
            if not p:
                print(f"  MISSING from DB: #{dp['id']} {dp['name']}")
                missing += 1
                continue
            if p.category != category:
                print(f"  CATEGORY MISMATCH: #{dp['id']} is '{p.category}', expected '{category}' -- skipped")
                missing += 1
                continue
            style_tags = dp.get("style_tags")
            occasion = dp.get("occasion")
            p.style_tags = json.dumps(style_tags) if style_tags else None
            p.occasion = json.dumps(occasion) if occasion else None
            session.add(p)
            updated += 1
        session.commit()

    print(f"\n{category}: {updated} updated, {missing} missing/mismatched (out of {len(demo_products)} in demo)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/backfill_style_occasion.py <demo_file> <category>")
        sys.exit(1)
    backfill(sys.argv[1], sys.argv[2])
