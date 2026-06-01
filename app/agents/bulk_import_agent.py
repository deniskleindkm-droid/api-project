from dotenv import load_dotenv
load_dotenv()

import os
import json
import anthropic
from datetime import datetime
from app.agents.store_config import get_config

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# COLLECTION SEARCH STRATEGIES
# Each collection has specific keywords and quality filters
# ARIA searches CJ using these — never random
# ============================================================

COLLECTION_STRATEGIES = {
    "Jewelry": {
        "config_key": "collection_jewelry",
        "default_id": 13,
        # CJ category IDs — populate from GET /cj/categories. Falls back to keywords if empty.
        "category_ids": ["2447", "2440", "2441", "2446"],  # Rings, Necklaces, Earrings, Bracelets
        "keywords": [
            "925 sterling silver ring",
            "gold plated necklace women",
            "sterling silver bracelet",
            "nose ring piercing",
            "zircon crystal earring",
            "gold plated pendant necklace",
            "stainless steel ring women",
            "silver anklet women",
            "crystal choker necklace",
            "gold plated bangle bracelet"
        ],
        "quality_keywords": ["925", "sterling", "gold plated", "stainless steel", "zircon", "crystal"],
        "reject_keywords": ["plastic", "acrylic", "resin", "cheap"],
        "max_per_run": 200
    },
    "Women Watches": {
        "config_key": "collection_watches",
        "default_id": 14,
        "category_ids": ["2476", "2477"],  # Women's Watches, Fashion Watches
        "keywords": [
            "women quartz watch elegant",
            "ladies stainless steel watch",
            "women leather strap watch",
            "rose gold women watch",
            "minimalist women wristwatch",
            "luxury style women watch"
        ],
        "quality_keywords": ["stainless steel", "quartz", "leather", "mineral glass", "sapphire"],
        "reject_keywords": ["plastic", "digital only", "rubber strap", "kids"],
        "max_per_run": 100
    },
    "Hair Accessories": {
        "config_key": "collection_hair_accessories",
        "default_id": 15,
        "category_ids": ["2387", "2388"],  # Hair Accessories, Hair Clips & Pins
        "keywords": [
            "claw clip hair women",
            "hair barrette elegant",
            "scrunchie silk satin",
            "headband women elegant",
            "hair pin pearl",
            "bobby pin set women",
            "hair comb decorative",
            "hair clip metal acetate"
        ],
        "quality_keywords": ["metal", "acetate", "silk", "satin", "pearl", "crystal"],
        "reject_keywords": ["kids", "baby", "cheap plastic"],
        "max_per_run": 150
    },
    "Makeup Accessories": {
        "config_key": "collection_makeup",
        "default_id": 16,
        "category_ids": ["2338", "2339"],  # Makeup Brushes & Tools, Beauty Applicators
        "keywords": [
            "makeup brush set professional",
            "beauty blender sponge",
            "foundation brush kabuki",
            "eyeshadow brush set",
            "cosmetic brush premium",
            "makeup applicator tool",
            "blush contour brush"
        ],
        "quality_keywords": ["professional", "dense", "soft bristle", "premium", "synthetic"],
        "reject_keywords": ["single use", "disposable", "kids"],
        "max_per_run": 100
    },
    "Skincare & Facial Tools": {
        "config_key": "collection_skincare",
        "default_id": 17,
        "category_ids": ["2314", "2315", "2316"],  # Skin Care Tools, Face Massagers, Facial Devices
        "keywords": [
            "jade roller face massager",
            "gua sha stone facial",
            "rose quartz roller",
            "face mask sheet korean",
            "vitamin c serum face",
            "hyaluronic acid serum",
            "facial cleansing brush",
            "microneedle derma roller",
            "led face mask beauty",
            "face lift tool beauty"
        ],
        "quality_keywords": ["jade", "quartz", "natural", "korean", "vitamin", "hyaluronic"],
        "reject_keywords": ["fake", "plastic stone", "harmful"],
        "max_per_run": 150
    },
    "Nail Care": {
        "config_key": "collection_nail_care",
        "default_id": 18,
        "category_ids": ["2351", "2352"],  # Nail Art Tools, Nail Accessories
        "keywords": [
            "nail art tools set",
            "cuticle pusher stainless",
            "nail file buffer set",
            "manicure pedicure kit",
            "nail gel polish set",
            "nail art stamping kit",
            "nail drill electric",
            "nail sticker decoration"
        ],
        "quality_keywords": ["stainless steel", "professional", "ergonomic", "electric"],
        "reject_keywords": ["kids", "toy", "fake"],
        "max_per_run": 100
    }
}


# ============================================================
# BATCH REWRITER
# Sends 10 products per API call — 10x cheaper than 1 per call
# ============================================================

def batch_rewrite_products(products: list, collection_name: str, collection_id: int) -> list:
    """
    Rewrite 10 products in one API call.
    Returns list of accepted products with Mikisi identity.
    """
    if not products:
        return []

    brand_voice = get_config("brand_voice", default="Mikisi is elegant, empowering, intimate.")

    # Build product list for prompt
    product_list = "\n".join([
        f"{i+1}. Name: {p.get('name', '')[:100]} | Category: {p.get('category', '')} | Price: ${p.get('final_price', 0):.2f}"
        for i, p in enumerate(products)
    ])

    prompt = f"""You are ARIA, the intelligence behind Mikisi — a premium women's beauty accessories store.

BRAND VOICE:
{brand_voice}

TARGET COLLECTION: {collection_name} (ID: {collection_id})

You are reviewing {len(products)} products for import into Mikisi.
For each product decide: accept or reject. If accepted, rewrite for Mikisi.

QUALITY RULES:
- Jewelry: must be 925 sterling silver, gold plated, or stainless steel. No cheap alloys.
- Watches: must have stainless steel case, quality movement. No plastic.
- Hair Accessories: quality materials only. No cheap plastic that breaks.
- Makeup: professional grade brushes and tools only.
- Skincare: real materials (jade, quartz, proven ingredients). No fakes.
- Nail Care: stainless steel tools. Professional grade.

PRODUCTS TO REVIEW:
{product_list}

For each product return:
- accepted: true/false
- mikisi_name: clean elegant name max 6 words (if accepted)
- mikisi_description: 2 emotional sentences in Mikisi voice (if accepted)
- rejection_reason: why rejected (if rejected)

Return ONLY a JSON array with {len(products)} objects in the same order:
[
  {{
    "index": 1,
    "accepted": true,
    "mikisi_name": "Rose Gold Crystal Ring",
    "mikisi_description": "Some pieces choose you back. Wear this as a quiet declaration of self.",
    "rejection_reason": null
  }},
  ...
]

Return ONLY valid JSON array. No other text."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        results = json.loads(text.strip())

        # Merge rewrite results back into products
        rewritten = []
        for i, result in enumerate(results):
            if i >= len(products):
                break
            product = products[i].copy()
            if result.get("accepted"):
                product["mikisi_name"] = result.get("mikisi_name", product.get("name", ""))[:100]
                product["mikisi_description"] = result.get("mikisi_description", "")
                product["accepted"] = True
                rewritten.append(product)
            else:
                print(f"[Bulk Import] ❌ Rejected: {product.get('name', '')[:40]} — {result.get('rejection_reason', '')}")

        return rewritten

    except Exception as e:
        print(f"[Bulk Import] Batch rewrite error: {e}")
        # On error — return products with raw names (don't lose them)
        return [{**p, "mikisi_name": p.get("name", "")[:100],
                 "mikisi_description": "", "accepted": True} for p in products]


# ============================================================
# SEARCH AND IMPORT PER COLLECTION
# ============================================================

def import_for_collection(collection_name: str, strategy: dict) -> dict:
    """
    Search CJ for products in this collection.
    Batch rewrite. Import accepted products.
    """
    from app.agents.cj_dropshipping import search_products, get_product_details
    from app.agents.store_manager import import_product_from_supplier
    from app.agents.store_config import get_config
    import json as _json

    collection_id = int(get_config(strategy["config_key"], default=str(strategy["default_id"])))
    markup = get_config("default_markup", default=7.0)
    max_products = strategy["max_per_run"]

    print(f"\n[Bulk Import] 🔍 Searching for {collection_name} products...")

    all_raw_products = []
    category_ids = strategy.get("category_ids", [])
    keywords = strategy["keywords"]

    if category_ids:
        # Primary: search by CJ category ID — more accurate than keyword matching
        print(f"[Bulk Import] Using category IDs: {category_ids}")
        per_category = max(5, max_products // len(category_ids))
        search_items = [("category", cid) for cid in category_ids]
    else:
        # Fallback: keyword search
        print(f"[Bulk Import] No category IDs — falling back to keyword search")
        per_category = max(3, max_products // len(keywords))
        search_items = [("keyword", kw) for kw in keywords]

    for search_type, search_value in search_items:
        try:
            if search_type == "category":
                results = search_products(category_id=search_value, limit=per_category)
            else:
                results = search_products(keyword=search_value, limit=per_category)
            for p in results:
                # Basic quality pre-filter before ARIA
                name_lower = p.get("productNameEn", "").lower()
                reject = any(rk in name_lower for rk in strategy.get("reject_keywords", []))
                if not reject:
                    sell_price = p.get("sellPrice", "0")
                    if isinstance(sell_price, str) and "-" in sell_price:
                        cost = float(sell_price.split("-")[0].strip())
                    else:
                        cost = float(sell_price) if sell_price else 0

                    if cost > 0:
                        # Fetch full product details to get all images
                        pid = p.get("pid", "")
                        full_product = None
                        try:
                            full_product = get_product_details(pid)
                        except:
                            pass

                        # Extract multiple images
                        all_images = []
                        if full_product:
                            image_set = full_product.get("productImageSet", [])
                            if isinstance(image_set, list):
                                all_images = [img for img in image_set if img][:5]
                            if not all_images:
                                main_img = full_product.get("productImage", "")
                                if main_img:
                                    all_images = [main_img]
                        else:
                            main_img = p.get("productImage", "")
                            if main_img:
                                all_images = [main_img]

                        all_raw_products.append({
                            "name": p.get("productNameEn", ""),
                            "category": p.get("categoryName", collection_name),
                            "description": full_product.get("description", p.get("productNameEn", "")) if full_product else p.get("productNameEn", ""),
                            "image_url": all_images[0] if all_images else p.get("productImage", ""),
                            "images": _json.dumps(all_images) if len(all_images) > 1 else None,
                            "cost_price": cost,
                            "final_price": round(cost * markup + 0.99, 2),
                            "supplier_product_id": pid,
                            "supplier_name": "CJDropshipping",
                            "stock": 999,
                            "shipping_days": 15,
                            "variants": full_product.get("variants", p.get("variants", [])) if full_product else p.get("variants", [])
                        })
        except Exception as e:
            print(f"[Bulk Import] Search error for '{search_value}': {e}")

    if not all_raw_products:
        print(f"[Bulk Import] No products found for {collection_name}")
        return {"collection": collection_name, "imported": 0, "rejected": 0}

    # Deduplicate by name
    seen = set()
    unique_products = []
    for p in all_raw_products:
        key = p["name"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique_products.append(p)

    print(f"[Bulk Import] Found {len(unique_products)} unique products for {collection_name}")

    # Limit to max
    unique_products = unique_products[:max_products]

    # Batch rewrite — 10 products per API call
    batch_size = 10
    all_accepted = []
    for i in range(0, len(unique_products), batch_size):
        batch = unique_products[i:i+batch_size]
        accepted = batch_rewrite_products(batch, collection_name, collection_id)
        all_accepted.extend(accepted)
        print(f"[Bulk Import] Batch {i//batch_size + 1}: {len(accepted)}/{len(batch)} accepted")

    print(f"[Bulk Import] {len(all_accepted)} products accepted for {collection_name}")

    # Import accepted products
    imported = 0
    for product in all_accepted:
        try:
            # Build standard product format
            standard = {
                "name": product["mikisi_name"],
                "category": product["category"],
                "description": product["mikisi_description"] or product["name"],
                "image_url": product["image_url"],
                "cost_price": product["cost_price"],
                "supplier_product_id": product["supplier_product_id"],
                "supplier_name": "CJDropshipping",
                "stock": 999,
                "shipping_days": 15,
                "variants": product.get("variants", [])
            }

            # Override rewriter in store manager — use our pre-rewritten data
            from app.agents.store_manager import add_product_to_store
            from app.agents.store_config import get_config as gc

            markup_val = gc("default_markup", default=7.0)
            cost = product["cost_price"]
            final_price = round(int(cost * markup_val) + 0.99, 2)
            original_price = round(int(final_price * 1.4) + 0.99, 2)
            discount = round((1 - final_price / original_price) * 100)

            cj_sku = ""
            variants = product.get("variants", [])
            if variants:
                cj_sku = variants[0].get("variantSku", "") or variants[0].get("vid", "")

            product_data = {
                "name": product["mikisi_name"],
                "brand": "Mikisi",
                "category": product["category"],
                "description": product["mikisi_description"] or product["name"],
                "original_price": original_price,
                "discount_percent": discount,
                "final_price": final_price,
                "image_url": product["image_url"],
                "images": product.get("images"),
                "stock": 999,
                "shipping_days": 15,
                "supplier_name": "CJDropshipping",
                "supplier_url": "",
                "cj_product_id": product["supplier_product_id"],
                "cj_sku": cj_sku,
                "collection_id": collection_id,
            }

            p_obj, status = add_product_to_store(product_data)
            if status == "added":
                imported += 1
                # Emit signal
                try:
                    from app.agents.nervous_system import emit
                    emit(
                        signal_type="PRODUCT_IMPORTED",
                        sender="bulk_import_agent",
                        payload={
                            "product_id": p_obj.id,
                            "name": product["mikisi_name"],
                            "collection_id": collection_id,
                            "store_price": final_price,
                            "cost_price": cost,
                            "supplier": "CJDropshipping"
                        },
                        priority=7
                    )
                except Exception as e:
                    print(f"[Bulk Import] Signal error: {e}")

        except Exception as e:
            print(f"[Bulk Import] Import error for {product.get('mikisi_name', '')}: {e}")

    rejected = len(unique_products) - len(all_accepted)
    print(f"[Bulk Import] ✅ {collection_name} complete — {imported} imported, {rejected} rejected")
    return {"collection": collection_name, "imported": imported, "rejected": rejected}


# ============================================================
# MAIN BULK IMPORT AGENT
# Runs every 24 hours from scheduler
# ============================================================

def run_bulk_import_agent():
    """
    Main bulk import loop.
    Searches CJ for each of our 6 collections.
    Batch rewrites with ARIA using Haiku (cheap).
    Imports accepted products with Mikisi identity.
    """
    print(f"\n[Bulk Import] 🚀 Starting bulk import — {datetime.utcnow()}")

    results = []
    total_imported = 0
    total_rejected = 0

    for collection_name, strategy in COLLECTION_STRATEGIES.items():
        try:
            result = import_for_collection(collection_name, strategy)
            results.append(result)
            total_imported += result.get("imported", 0)
            total_rejected += result.get("rejected", 0)
        except Exception as e:
            print(f"[Bulk Import] Error on {collection_name}: {e}")
            results.append({"collection": collection_name, "imported": 0, "error": str(e)})

    print(f"\n[Bulk Import] ✅ Complete — {total_imported} imported, {total_rejected} rejected")
    print(f"[Bulk Import] Summary: {results}")

    # Save to memory
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            memory = AgentMemory(
                agent_name="bulk_import_agent",
                memory_type="import_run",
                content=json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "total_imported": total_imported,
                    "total_rejected": total_rejected,
                    "results": results
                }),
                confidence=0.9
            )
            session.add(memory)
            session.commit()
    except Exception as e:
        print(f"[Bulk Import] Memory save error: {e}")

    return {
        "total_imported": total_imported,
        "total_rejected": total_rejected,
        "results": results
    }