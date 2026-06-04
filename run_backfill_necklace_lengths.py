# -*- coding: utf-8 -*-
"""
Backfill chain lengths for all existing necklace products.

Extracts chain lengths from the already-stored variants JSON, which contains
the raw Silverbene option attributes. Handles all known patterns:
  - Size attribute: "45cm", "40cm", "450mm"
  - Color attribute: "1.0mm, 40cm"  (length hidden in color field)
  - Chain Length / Length attribute: "400mm - 450mm Adjustable"
  - Description HTML: <li>Chain Length: 450mm</li>

Products where no length is found get a default set + needs_length_review=True.
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

DEFAULT_SIZES = ['400mm / 16"', '450mm / 18"', '500mm / 20"']

LENGTH_PATTERN = re.compile(r'\d+\s*(mm|cm)', re.I)

SIZE_LIKE_NAMES = {"size", "ring size", "length", "bracelet size",
                   "anklet size", "chain length"}
COLOR_NAMES = {"color", "colour", "metal color", "metal finish", "finish"}


def _chips_from_variants(variants_json: str) -> list:
    """Parse chain length chips from stored variants JSON."""
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

        # Skip only if already converted AND not flagged for review
        if current and _already_converted(current) and not p.needs_length_review:
            already_ok += 1
            continue

        chips = []

        # 1. Parse from stored variants JSON
        chips = _chips_from_variants(p.variants)

        # 2. Fallback: parse from description HTML
        if not chips and p.description:
            chips = _parse_chain_length_from_desc(p.description)

        if chips:
            p.sizes = json.dumps(chips)
            p.needs_length_review = False
            updated += 1
            print("  OK  [%d] %s" % (p.id, p.name[:55]))
            print("       -> %s" % chips)
        else:
            p.sizes = json.dumps(DEFAULT_SIZES)
            p.needs_length_review = True
            defaulted += 1
            print("  DEFAULT  [%d] %s (needs_length_review=True)" % (p.id, p.name[:55]))

        session.add(p)

    session.commit()

print("\n=== BACKFILL COMPLETE ===")
print("  Total necklaces:     %d" % total)
print("  Already correct:     %d" % already_ok)
print("  Updated with data:   %d" % updated)
print("  Defaulted (flagged): %d" % defaulted)
