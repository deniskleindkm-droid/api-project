# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, json
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

import anthropic
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

PROMPT_TEMPLATE = (
    "You are ARIA for Mikisi, a luxury women's jewelry brand.\n\n"
    "Product: {name}\nCategory: {category}\nMaterial: {material}\n\n"
    "Do exactly three things:\n"
    "1. CLEAN NAME - max 6 words, strip supplier jargon, model codes, '925', 'sterling silver', 'adjustable ring'. Keep the essence.\n"
    "2. IDENTIFY MATERIAL - exactly what it is (e.g. '925 Sterling Silver', '18k Gold Plated 925 Silver').\n"
    "3. WRITE DESCRIPTION - exactly 2 sentences. Intimate, empowering, elegant. Mention the material in sentence 1.\n\n"
    'Return ONLY valid JSON (no markdown):\n'
    '{{"mikisi_name": "...", "mikisi_material": "...", "mikisi_description": "..."}}'
)


def rewrite_one(name, category, material):
    prompt = PROMPT_TEMPLATE.format(
        name=name[:120],
        category=category,
        material=material or 'not specified'
    )
    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=512,
        messages=[{'role': 'user', 'content': prompt}]
    )
    text = msg.content[0].text.strip() if msg.content else ''
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    return None


with Session(engine) as session:
    products = session.exec(select(Product).where(Product.is_active == True)).all()
    raw = [
        p for p in products
        if p.description and p.name
        and p.description.strip()[:80] == p.name.strip()[:80]
    ]
    print(f'Rewriting {len(raw)} products one by one...\n')

    for p in raw:
        try:
            result = rewrite_one(p.name, p.category, p.material or '')
            if result:
                old_name = p.name[:50]
                if result.get('mikisi_name'):
                    p.name = result['mikisi_name'][:100]
                if result.get('mikisi_description') and result['mikisi_description'] != p.name:
                    p.description = result['mikisi_description']
                if result.get('mikisi_material'):
                    p.material = result['mikisi_material']
                session.add(p)
                print(f'  OK  {old_name:50s}  ->  {p.name}')
            else:
                print(f'  SKIP (no result): {p.name[:60]}')
        except Exception as e:
            print(f'  ERR  {p.name[:50]}: {e}')

    session.commit()
    print('\nDone.')
