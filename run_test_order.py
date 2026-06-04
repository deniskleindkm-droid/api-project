# -*- coding: utf-8 -*-
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

# ── Step 1: find cheapest product ────────────────────────────
with Session(engine) as session:
    product = session.exec(
        select(Product).where(Product.is_active == True).order_by(Product.final_price)
    ).first()

    pid        = product.id
    name       = product.name
    category   = product.category
    price      = product.final_price
    cost       = product.silverbene_cost
    material   = product.material
    stock      = product.stock
    sku        = product.cj_product_id   # Silverbene SKU
    option_id  = product.cj_sku          # first option_id
    variants   = json.loads(product.variants) if product.variants else []

print("=" * 60)
print("  CHEAPEST PRODUCT")
print("=" * 60)
print(f"  ID:          {pid}")
print(f"  Name:        {name}")
print(f"  Category:    {category}")
print(f"  Store price: ${price}")
print(f"  Cost:        ${cost}")
print(f"  Material:    {material}")
print(f"  Stock:       {stock}")
print(f"  SKU:         {sku}")
print(f"  Option ID:   {option_id}")
print(f"  Variants:    {len(variants)}")
for v in variants[:3]:
    print(f"    {v}")

# ── Step 2: check live stock via Silverbene API ───────────────
print("\n" + "=" * 60)
print("  STOCK CHECK (Silverbene live API)")
print("=" * 60)

from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
adapter = SilverbeneAdapter()

# Build comma-separated option_ids for stock check
option_ids = [str(v.get("option_id")) for v in variants if v.get("option_id")]
live_stock = 0
if option_ids:
    # Check first option
    live_stock = adapter.get_stock(option_ids[0])
    print(f"  Option {option_ids[0]}: {live_stock} units in stock")
    if len(option_ids) > 1:
        print(f"  (checking first option only; product has {len(option_ids)} variants)")
else:
    print("  No option_ids found in variants")

can_fulfill = live_stock > 0

# ── Step 3: get shipping methods ─────────────────────────────
print("\n" + "=" * 60)
print("  SHIPPING CHECK (Silverbene live API)")
print("=" * 60)

shipping_methods = adapter.get_shipping_methods("US", option_id=use_option_id if 'use_option_id' in dir() else (option_ids[0] if option_ids else None))
if shipping_methods:
    for m in shipping_methods[:5]:
        print(f"  {m}")
else:
    print("  No shipping methods returned")

# ── Step 4: simulate order placement (DRY RUN) ───────────────
print("\n" + "=" * 60)
print("  ORDER SIMULATION (dry run — NOT placing real order)")
print("=" * 60)

test_customer = {
    "first_name": "Test",
    "last_name":  "Customer",
    "email":      "test@mikisi.com",
    "phone":      "+12125551234",
}
test_address = {
    "line1":        "123 Test Street",
    "city":         "New York",
    "state":        "New York",
    "state_code":   "NY",
    "postal_code":  "10001",
    "country_code": "US",
}

use_option_id = option_ids[0] if option_ids else option_id

print(f"  Product SKU:  {sku}")
print(f"  Option ID:    {use_option_id}")
print(f"  Ship to:      {test_address['city']}, {test_address['state_code']} {test_address['postal_code']}")
print(f"  Customer:     {test_customer['first_name']} {test_customer['last_name']}")

# Build the payload without placing a real order
methods = adapter.get_shipping_methods(test_address["country_code"], option_id=use_option_id)
carrier_code = methods[0].get("carrier_code", "") if methods else ""
method_code  = methods[0].get("method_code", "")  if methods else ""

payload = {
    "options": [{"option_id": str(use_option_id), "qty": 1}],
    "shipping_address": {
        "firstname":   test_customer["first_name"],
        "lastname":    test_customer["last_name"],
        "email":       test_customer["email"],
        "telephone":   test_customer["phone"],
        "street":      test_address["line1"],
        "city":        test_address["city"],
        "region":      test_address["state"],
        "region_code": test_address["state_code"],
        "postcode":    test_address["postal_code"],
        "country_id":  test_address["country_code"],
    },
    "shipping_carrier_code": carrier_code,
    "shipping_method_code":  method_code,
}

print("\n  Order payload that would be sent to Silverbene:")
print(f"  {json.dumps(payload, indent=4)}")

# ── Step 5: verdict ───────────────────────────────────────────
print("\n" + "=" * 60)
print("  FULFILLMENT VERDICT")
print("=" * 60)

issues = []
if not can_fulfill:
    issues.append("STOCK: product shows 0 units at Silverbene")
if not option_ids:
    issues.append("OPTION ID: no option_id found — cannot place order")
if not carrier_code:
    issues.append("SHIPPING: no carrier/method returned by Silverbene API")

if not issues:
    print("  RESULT: CAN FULFILL")
    print(f"  - Live stock confirmed: {live_stock} units")
    print(f"  - Option ID ready: {use_option_id}")
    print(f"  - Store price: ${price} (cost ${cost} + $18 shipping + Stripe)")
else:
    print("  RESULT: CANNOT FULFILL — issues found:")
    for issue in issues:
        print(f"  - {issue}")
