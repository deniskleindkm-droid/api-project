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

COLLECTION = {'Rings':104,'Necklaces':105,'Bracelets':106,'Earrings':107,'Anklets':108,'Ear Cuffs':109}

def detect_true_category(name):
    n = name.lower()
    if any(w in n for w in ['ear cuff','ear clip']):
        return 'Ear Cuffs'
    if any(w in n for w in ['earring','studs',' stud','huggie',' hoop','hoops','drop earr','dangle earr','cartilage earr']):
        return 'Earrings'
    if any(w in n for w in ['necklace','pendant chain','bead necklace']):
        return 'Necklaces'
    if any(w in n for w in ['bracelet','bangle']):
        return 'Bracelets'
    if 'anklet' in n:
        return 'Anklets'
    return None

def is_raw(p):
    return (p.description and p.name and
            p.description.strip()[:80] == p.name.strip()[:80])

def has_junk_name(name):
    junk = ['925 sterling silver','s925','sterling silver','adjustable ring',
            'fashion ','casual ','women ','ladies ','female ','style ',
            'for her','dropshipping','commuter']
    n = name.lower()
    return any(j in n for j in junk) or len(name) > 60

with Session(engine) as session:
    products = session.exec(select(Product).where(Product.is_active==True)).all()

    wrong_cat   = []
    raw_desc    = []
    junk_names  = []

    for p in products:
        true_cat = detect_true_category(p.name)
        if true_cat and true_cat != p.category:
            wrong_cat.append((p, true_cat))
        if is_raw(p):
            raw_desc.append(p)
        elif has_junk_name(p.name):
            junk_names.append(p)

    print(f'Total active products: {len(products)}')
    print(f'Wrong category:        {len(wrong_cat)}')
    print(f'Raw descriptions:      {len(raw_desc)}')
    print(f'Junk names:            {len(junk_names)}')

    if wrong_cat:
        print('\n=== WRONG CATEGORY ===')
        for p, tc in wrong_cat:
            print(f'  [{p.id}] {p.category} -> {tc}: {p.name[:60]}')

    if raw_desc:
        print(f'\n=== RAW DESCRIPTIONS ({len(raw_desc)}) ===')
        for p in raw_desc:
            print(f'  [{p.id}] {p.category}: {p.name[:60]}')

    if junk_names:
        print(f'\n=== JUNK NAMES ({len(junk_names)}) ===')
        for p in junk_names:
            print(f'  [{p.id}] {p.category}: {p.name[:70]}')
