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
    "Rings": {
        "config_key": "collection_rings",
        "default_id": 1,
        "markup_key": "markup_rings",
        "default_markup": 8.0,
        "category_ids": [
            "56B4F8B6-8600-4A18-913E-53F2F693EC2C",  # Rings
            "FCE034F6-A2BF-47E3-852F-FA9F67F904B2",  # Engagement Rings
            "552F095A-904C-40E4-A43B-0CD1CE15D29F",  # 925 Silver Jewelry
        ],
        "keywords": [
            "925 sterling silver ring women",
            "gold plated ring women",
            "stainless steel ring",
            "gemstone ring silver",
            "crystal ring women",
            "engagement ring silver",
            "stackable ring set silver",
        ],
        "quality_keywords": ["925", "sterling silver", "gold plated", "stainless steel", "titanium", "gemstone"],
        "reject_keywords": ["plastic", "acrylic", "resin", "rubber"],
        "max_per_run": 100,
    },
    "Necklaces": {
        "config_key": "collection_necklaces",
        "default_id": 2,
        "markup_key": "markup_necklaces",
        "default_markup": 7.0,
        "category_ids": [
            "95D9F317-1DB3-4E42-A031-02223215B9C5",  # Necklace & Pendants
            "84ED4B7F-D7C3-412F-AF18-04F25C91985C",  # Pearls Jewelry
        ],
        "keywords": [
            "925 sterling silver necklace",
            "gold plated pendant necklace women",
            "stainless steel necklace",
            "crystal pendant necklace",
            "choker necklace silver",
            "chain necklace women gold",
        ],
        "quality_keywords": ["925", "sterling silver", "gold plated", "stainless steel", "pendant", "chain"],
        "reject_keywords": ["plastic", "acrylic", "resin"],
        "max_per_run": 80,
    },
    "Bracelets": {
        "config_key": "collection_bracelets",
        "default_id": 3,
        "markup_key": "markup_bracelets",
        "default_markup": 7.0,
        "category_ids": [
            "0615F8DB-C10F-4BEF-892B-1C5B04268938",  # Bracelets & Bangles
        ],
        "keywords": [
            "925 sterling silver bracelet",
            "gold plated bangle bracelet",
            "stainless steel bracelet women",
            "crystal charm bracelet",
            "chain bracelet silver women",
            "cuff bracelet gold",
        ],
        "quality_keywords": ["925", "sterling silver", "gold plated", "stainless steel", "bangle", "cuff"],
        "reject_keywords": ["plastic", "rubber", "acrylic"],
        "max_per_run": 80,
    },
    "Earrings": {
        "config_key": "collection_earrings",
        "default_id": 4,
        "markup_key": "markup_earrings",
        "default_markup": 8.0,
        "category_ids": [
            "D28405AE-66C6-42E6-BFF0-D6FDCB5C083C",  # Earrings
            "D7CE9827-F50A-4B07-84BF-1BFE44188A1C",  # Fine Earrings
        ],
        "keywords": [
            "925 sterling silver earrings women",
            "gold plated hoop earrings",
            "stainless steel stud earrings",
            "crystal drop earrings women",
            "pearl earrings silver",
            "zircon earrings gold",
        ],
        "quality_keywords": ["925", "sterling silver", "gold plated", "stainless steel", "zircon", "pearl", "crystal"],
        "reject_keywords": ["plastic", "acrylic", "resin", "kids"],
        "max_per_run": 100,
    },
    "Anklets": {
        "config_key": "collection_anklets",
        "default_id": 5,
        "markup_key": "markup_anklets",
        "default_markup": 6.0,
        "category_ids": [
            "2601070548141611900",  # Anklets
        ],
        "keywords": [
            "925 sterling silver anklet women",
            "gold plated anklet bracelet",
            "stainless steel ankle bracelet",
            "crystal anklet women",
            "beach anklet silver",
        ],
        "quality_keywords": ["925", "sterling silver", "gold plated", "stainless steel"],
        "reject_keywords": ["plastic", "rubber", "fabric"],
        "max_per_run": 50,
    },
    "Piercings & Body Jewelry": {
        "config_key": "collection_piercings",
        "default_id": 6,
        "markup_key": "markup_piercings",
        "default_markup": 7.0,
        "category_ids": [
            "633E1860-7C63-4006-AB35-3FC16BECFA62",  # Body Jewelry
        ],
        "keywords": [
            "nose ring stud surgical steel",
            "cartilage earring stud titanium",
            "belly button ring surgical steel",
            "nose hoop piercing silver",
            "body jewelry surgical steel",
        ],
        "quality_keywords": ["surgical steel", "titanium", "925 silver", "implant grade"],
        "reject_keywords": ["plastic", "acrylic", "cheap"],
        "max_per_run": 60,
    },
}


def _calculate_price(cost: float, collection_name: str, product_name: str) -> tuple:
    """
    Mikisi intelligent pricing formula.
    Final price = Cost × Base × Quality × Supplier, minimum $10.99, rounded to .99
    Returns (final_price, original_price, discount_percent)
    """
    strategy = COLLECTION_STRATEGIES.get(collection_name, {})
    base = float(get_config(strategy.get("markup_key", "markup_rings"),
                             default=strategy.get("default_markup", 7.0)))

    name_lower = product_name.lower()
    if "moissanite" in name_lower:
        quality = float(get_config("quality_moissanite", default=2.5))
    elif "925" in name_lower or "sterling silver" in name_lower:
        quality = float(get_config("quality_925_silver", default=1.4))
    elif "natural" in name_lower and ("stone" in name_lower or "gem" in name_lower):
        quality = float(get_config("quality_natural_gemstone", default=2.0))
    elif "pvd" in name_lower:
        quality = float(get_config("quality_pvd_plating", default=1.2))
    elif "18k" in name_lower or "gold plated" in name_lower:
        quality = float(get_config("quality_18k_gold_plated", default=1.1))
    else:
        quality = float(get_config("quality_unknown_material", default=0.8))

    supplier = float(get_config("supplier_cj", default=1.0))
    min_price = float(get_config("min_price", default=10.99))

    computed = cost * base * quality * supplier
    final_price = max(min_price, round(computed - 0.01, 0) + 0.99)
    original_price = round(final_price * 1.4 - 0.01, 0) + 0.99
    discount = round((1 - final_price / original_price) * 100)
    return final_price, original_price, discount


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

    prompt = f"""You are ARIA, the intelligence behind Mikisi — a luxury jewelry brand for women who choose themselves.

BRAND VOICE:
{brand_voice}

TARGET COLLECTION: {collection_name} (ID: {collection_id})

You are reviewing {len(products)} jewelry products for import into Mikisi.
For each product decide: accept or reject. If accepted, rewrite for Mikisi.

QUALITY RULES — NON NEGOTIABLE:
- Metal must be specified: 925 sterling silver, 18k gold plated, stainless steel, titanium, or surgical steel
- Unknown or unspecified metal = automatic rejection
- Absolutely no plastic, acrylic, or resin jewelry — ever
- Must be wearable jewelry only (rings, necklaces, bracelets, earrings, anklets, piercings)
- Reject anything that is not jewelry

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

            from app.agents.store_manager import add_product_to_store

            cost = product["cost_price"]
            final_price, original_price, discount = _calculate_price(
                cost, collection_name, product["mikisi_name"]
            )

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
                "variants": json.dumps(product.get("variants", [])) if product.get("variants") else None,
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