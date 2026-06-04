# -*- coding: utf-8 -*-
"""
One-shot script:
1. Apply DB migrations (new pricing columns)
2. Reprice all existing Silverbene products with the new engine
3. Run bulk import -- 10 products per collection
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from sqlmodel import Session, select
from app.database import engine, create_db
from app.models.product import Product
from app.agents.jewelry_pricing import calculate_mikisi_price, detect_material
import json


def reprice_existing():
    """Reprice every existing Silverbene product with the new formula."""
    updated = 0
    skipped = 0

    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.supplier_name == "Silverbene",
                Product.is_active == True,
            )
        ).all()

        print(f"\n[Reprice] Found {len(products)} existing Silverbene products")

        for p in products:
            cost = p.silverbene_cost
            if not cost or cost <= 0:
                print(f"  SKIP  {p.name[:50]} -- no stored cost (needs fresh import)")
                skipped += 1
                continue

            # Try to extract raw options from variants JSON for better material detection
            raw_options = []
            if p.variants:
                try:
                    raw_options = json.loads(p.variants)
                except Exception:
                    pass

            material_key = detect_material(p.name, raw_options)
            pricing = calculate_mikisi_price(cost, material_key)

            old_price = p.final_price
            p.final_price      = pricing["final_price"]
            p.original_price   = pricing["original_price"]
            p.discount_percent = pricing["discount_percent"]
            p.shipping_cost    = pricing["shipping_cost"]
            p.markup_used      = pricing["markup_used"]
            p.last_price_sync  = datetime.utcnow()
            p.is_premium       = material_key == "moissanite"
            p.needs_review     = (p.silverbene_cost or 0) > 40

            session.add(p)
            updated += 1
            print(f"  OK  {p.name[:50]:50s}  {material_key:15s}  ${old_price:.2f} -> ${pricing['final_price']:.2f}")

        session.commit()

    print(f"\n[Reprice] Done — {updated} repriced, {skipped} skipped\n")
    return updated


def run_import():
    from app.agents.bulk_import_agent import run_bulk_import_agent
    print("\n[Import] Starting bulk import — 10 products per collection\n")
    result = run_bulk_import_agent(max_per_collection=10)
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("  MIKISI — Reprice + Import")
    print("=" * 60)

    # Step 1: apply DB migrations
    print("\n[DB] Applying migrations...")
    try:
        create_db()
        print("[DB] Migrations applied")
    except Exception as e:
        print(f"[DB] Migration warning (may already exist): {e}")

    # Step 2: reprice existing products
    reprice_existing()

    # Step 3: bulk import 10 per collection
    result = run_import()

    print("\n" + "=" * 60)
    print(f"  Total imported: {result.get('total_imported', 0)}")
    print(f"  Total rejected: {result.get('total_rejected', 0)}")
    print("=" * 60)
