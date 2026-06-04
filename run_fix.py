# -*- coding: utf-8 -*-
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

COLLECTION = {
    'Rings': 104, 'Necklaces': 105, 'Bracelets': 106,
    'Earrings': 107, 'Anklets': 108, 'Ear Cuffs': 109, 'Jewelry Sets': 110
}


def detect_true_category(name):
    n = name.lower()
    if any(w in n for w in ['earring', 'studs', ' stud', ' hoop', 'hoops', 'huggie',
                             'drop earr', 'dangle earr', 'tassel earr', 'cartilage earr',
                             'birthstone earr', 'ear cuff']):
        if 'ear cuff' in n:
            return 'Ear Cuffs'
        return 'Earrings'
    if any(w in n for w in ['necklace', ' pendant', 'bead necklace', 'chain necklace']):
        return 'Necklaces'
    if any(w in n for w in ['bracelet', 'bangle']):
        return 'Bracelets'
    if 'anklet' in n:
        return 'Anklets'
    return None


def is_sku_code(val):
    v = val.strip()
    if re.match(r'^Option_[a-f0-9]+', v, re.I):
        return True
    color_words = {
        'silver', 'gold', 'rose', 'white', 'black', 'yellow', 'pink', 'blue', 'green', 'red',
        'rhodium', 'platinum', 'mm', 'cm', 'small', 'large', 'medium', 'single', 'pair',
        'vintage', 'retro', 'narrow', 'wide', 'turquoise', 'crystal', 'pearl', 'stone',
        'cz', 'enamel', 'matte', 'polished', 'mixed', 'multicolor', 'colorful', 'cross',
        'double', 'layer', 'style', 'type', 'transparent', 'clear', 'oval', 'heart', 'star',
        'purple', 'brown', 'orange', 'gray', 'grey', 'navy', 'teal', 'nude'
    }
    lower = v.lower()
    if re.match(r'^[a-z]{1,5}[0-9]', lower) and not any(c in lower for c in color_words):
        return True
    if '925 sterling silver' in lower and any(c in lower for c in ['ring', 'anklet', 'bracelet', 'chain']):
        return True
    return False


def needs_aria_rewrite(p):
    return (p.description and p.name and
            p.description.strip()[:80] == p.name.strip()[:80])


moved_earrings = 0
moved_necklaces = 0
moved_ear_cuffs = 0
deactivated = 0
color_cleaned = 0
size_fixed = 0
needs_rewrite = []

with Session(engine) as session:
    products = session.exec(select(Product).where(Product.is_active == True)).all()

    for p in products:
        changed = False

        # 1. Fix category misplacements
        true_cat = detect_true_category(p.name)
        if true_cat and true_cat != p.category:
            print(f'MOVE  {p.category:12s} -> {true_cat:12s}: {p.name[:55]}')
            p.category = true_cat
            p.collection_id = COLLECTION[true_cat]
            if true_cat == 'Earrings':
                p.sizes = None
                moved_earrings += 1
            elif true_cat == 'Necklaces':
                moved_necklaces += 1
            elif true_cat == 'Ear Cuffs':
                moved_ear_cuffs += 1
            changed = True

        # 2. Deactivate men's products
        if p.name.lower().startswith("men's") or p.name.lower().startswith("men "):
            print(f'DEACTIVATE (mens): {p.name[:60]}')
            p.is_active = False
            deactivated += 1
            changed = True

        # 3. Clean SKU/hash codes from colors
        if p.colors:
            try:
                raw = json.loads(p.colors)
                cleaned = [v for v in raw if not is_sku_code(v)]
                if cleaned != raw:
                    removed = [v for v in raw if is_sku_code(v)]
                    print(f'COLORS  {p.name[:40]}: removed {removed}')
                    p.colors = json.dumps(cleaned) if cleaned else None
                    color_cleaned += 1
                    changed = True
            except Exception:
                pass

        # 4. Normalize bad size values
        if p.sizes:
            try:
                sizes = json.loads(p.sizes)
                normalized = []
                for s in sizes:
                    sl = s.lower().strip()
                    if sl in ('retro', 'vintage', 'one size', 'adjustable open ring',
                              'adjustable', 'open adjustable', 'open ring'):
                        normalized.append('One Size / Adjustable')
                    else:
                        normalized.append(s)
                normalized = list(dict.fromkeys(normalized))
                if normalized != sizes:
                    print(f'SIZES   {p.name[:40]}: {sizes} -> {normalized}')
                    p.sizes = json.dumps(normalized)
                    size_fixed += 1
                    changed = True
            except Exception:
                pass

        # 5. Fix Minimalist Box Chain: move chain specs from colors -> sizes
        if p.name == 'Minimalist Box Chain' and p.colors:
            try:
                raw = json.loads(p.colors)
                print(f'CHAIN   Moving {len(raw)} chain specs from colors to sizes')
                p.sizes = json.dumps(raw)
                p.colors = None
                size_fixed += 1
                changed = True
            except Exception:
                pass

        # 6. Track products needing ARIA rewrite
        if needs_aria_rewrite(p) and p.is_active:
            needs_rewrite.append(p)

        if changed:
            session.add(p)

    session.commit()
    print(f'\n--- PHASE 1 COMPLETE ---')
    print(f'Moved to Earrings:  {moved_earrings}')
    print(f'Moved to Necklaces: {moved_necklaces}')
    print(f'Moved to Ear Cuffs: {moved_ear_cuffs}')
    print(f'Deactivated (mens): {deactivated}')
    print(f'Colors cleaned:     {color_cleaned}')
    print(f'Sizes normalized:   {size_fixed}')
    print(f'Need ARIA rewrite:  {len(needs_rewrite)}')

# Phase 2: ARIA rewrite for raw-description products
if needs_rewrite:
    print(f'\n--- PHASE 2: ARIA REWRITE ({len(needs_rewrite)} products) ---')
    from app.agents.bulk_import_agent import batch_rewrite_products
    import math

    batch_size = 10
    total_rewritten = 0

    for i in range(0, len(needs_rewrite), batch_size):
        batch = needs_rewrite[i:i + batch_size]
        collection_name = batch[0].category

        aria_input = [
            {
                'name': p.name,
                'material': p.material or '',
                'colors': p.colors,
                'description': p.description,
                'category': p.category,
            }
            for p in batch
        ]

        results = batch_rewrite_products(aria_input, collection_name, 0)

        with Session(engine) as session:
            for j, result in enumerate(results):
                if j >= len(batch):
                    break
                p = session.get(Product, batch[j].id)
                if not p:
                    continue
                new_name = result.get('mikisi_name', '').strip()
                new_desc = result.get('mikisi_description', '').strip()
                new_mat  = result.get('material', '').strip()
                if new_name and len(new_name) < 100:
                    p.name = new_name
                if new_desc and new_desc != new_name:
                    p.description = new_desc
                if new_mat:
                    p.material = new_mat
                session.add(p)
                total_rewritten += 1
                print(f'  REWRITE [{j+1}/{len(batch)}] {batch[j].name[:40]} -> {new_name}')
            session.commit()

        print(f'Batch {i//batch_size + 1} done')

    print(f'\nARIA rewrote {total_rewritten} products')

print('\n=== ALL FIXES COMPLETE ===')

# Final count
with Session(engine) as session:
    from sqlmodel import func
    by_cat = session.exec(
        select(Product.category, func.count()).where(Product.is_active == True).group_by(Product.category)
    ).all()
    print('\nFinal product counts:')
    for cat, count in sorted(by_cat):
        print(f'  {cat:<20} {count}')
