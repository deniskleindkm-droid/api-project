# -*- coding: utf-8 -*-
"""
Backfill chain lengths for all existing necklace products.

Strategy:
  1. Parse from stored variants JSON (Size/Color/Chain Length attributes)
  2. Fallback: parse from description HTML
  3. If no data → set "450mm / 18\"" (standard pendant chain) + flag needs_length_review
     Pendants that only have color variants come with a standard 18" chain.

Run once: python run_backfill_necklace_lengths.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, json, re
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

# Standard pendant chain — comes with nearly all Silverbene pendant necklaces
PENDANT_DEFAULT = ['450mm / 18"']

LENGTH_PATTERN = re.compile(r'\d+\s*(mm|cm)', re.I)
SIZE_LIKE_NAMES = {"size", "ring size", "length", "bracelet size", "anklet size", "chain length"}
COLOR_NAMES = {"color", "colour", "metal color", "metal finish", "finish"}


def _chips_from_variants(variants_json: str) -> list:
    if not variants_json:
        return []
    try:
        options = json.loads(variants_json)
    except Exception:
        return []

    chips = []
    seen = set()

    for opt in (options if isinstance(options, list) else []):
        for attr in opt.get("attribute", []):
            name = attr.get("name", "").lower().strip()
            value = attr.get("value", "").strip()
            if not value:
                continue

            is_length_value = bool(LENGTH_PATTERN.search(value))

            if name in ("chain length", "length") and is_length_value:
                parsed = parse_necklace_length(value)
            elif name == "size" and is_length_value:
                parsed = parse_necklace_length(value)
            elif name in COLOR_NAMES and re.search(r'\d+\s*cm', value, re.I):
                parsed = parse_necklace_length(value)
            else:
                continue

            for chip in parsed:
                if chip not in seen:
                    seen.add(chip)
                    chips.append(chip)

    return chips


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

    print("Necklaces found: %d\n" % total)

    for p in necklaces:
        current = []
        if p.sizes:
            try:
                current = json.loads(p.sizes)
            except Exception:
                pass

        if current and _already_converted(current) and not p.needs_length_review:
            already_ok += 1
            continue

        chips = _chips_from_variants(p.variants)

        if not chips and p.description:
            chips = _parse_chain_length_from_desc(p.description)

        if chips:
            p.sizes = json.dumps(chips)
            p.needs_length_review = False
            updated += 1
            print("  OK  [%d] %s" % (p.id, p.name[:55]))
            print("       -> %s" % chips)
        else:
            # No length data anywhere — standard 18" pendant chain
            p.sizes = json.dumps(PENDANT_DEFAULT)
            p.needs_length_review = True
            defaulted += 1
            print("  PENDANT DEFAULT  [%d] %s" % (p.id, p.name[:55]))

        session.add(p)

    session.commit()

print("\n=== BACKFILL COMPLETE ===")
print("  Total necklaces:     %d" % total)
print("  Already correct:     %d" % already_ok)
print("  Updated with data:   %d" % updated)
print("  Pendant default (18\"): %d  (needs_length_review=True)" % defaulted)
