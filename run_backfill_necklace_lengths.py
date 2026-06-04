# -*- coding: utf-8 -*-
"""
Backfill chain lengths for all existing necklace products.

For each necklace where sizes is null or empty:
  1. Parse chain length from the stored description HTML
  2. If found  → store parsed chips (e.g. ["400mm / 16\"", "450mm / 18\""])
  3. If missing → set default 3 sizes + flag needs_length_review = True

Run once via Railway one-off command or locally with DATABASE_URL set.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, json
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product
from app.agents.suppliers.silverbene_adapter import (
    parse_necklace_length,
    _parse_chain_length_from_desc,
)

DEFAULT_SIZES = ['400mm / 16"', '450mm / 18"', '500mm / 20"']


def _current_sizes(p: Product) -> list:
    if not p.sizes:
        return []
    try:
        return json.loads(p.sizes)
    except Exception:
        return []


def _already_converted(sizes: list) -> bool:
    return any("/" in s for s in sizes)


with Session(engine) as session:
    necklaces = session.exec(
        select(Product).where(
            Product.category == "Necklaces",
            Product.is_active == True,
        )
    ).all()

    total = len(necklaces)
    updated = 0
    defaulted = 0
    already_ok = 0
    converted_raw = 0

    print(f"Necklaces found: {total}\n")

    for p in necklaces:
        current = _current_sizes(p)

        # Already has converted chips (contains "/") — leave it alone
        if current and _already_converted(current):
            already_ok += 1
            continue

        chips = []

        # 1. Try to convert existing raw mm sizes (e.g. ["450mm"] from old import)
        if current:
            for raw_val in current:
                import re
                if re.search(r'\d+\s*mm', raw_val, re.I):
                    chips = parse_necklace_length(raw_val)
                    if chips:
                        break

        # 2. Parse from description HTML
        if not chips and p.description:
            chips = _parse_chain_length_from_desc(p.description)

        if chips:
            p.sizes = json.dumps(chips)
            p.needs_length_review = False
            updated += 1
            print(f"  OK  [{p.id}] {p.name[:55]}")
            print(f"       -> {chips}")
        else:
            # No length data found — apply default + flag for review
            p.sizes = json.dumps(DEFAULT_SIZES)
            p.needs_length_review = True
            defaulted += 1
            print(f"  DEFAULT  [{p.id}] {p.name[:55]} (needs_length_review=True)")

        session.add(p)

    session.commit()

print(f"\n=== BACKFILL COMPLETE ===")
print(f"  Total necklaces:     {total}")
print(f"  Already correct:     {already_ok}")
print(f"  Updated with data:   {updated}")
print(f"  Defaulted (flagged): {defaulted}")
print(f"\nProducts with needs_length_review=True should be manually verified.")
