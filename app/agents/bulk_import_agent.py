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
        "default_id": 0,
        "cj_category_ids": [
            "56B4F8B6-8600-4A18-913E-53F2F693EC2C",  # Rings
            "FCE034F6-A2BF-47E3-852F-FA9F67F904B2",  # Engagement Rings
        ],
        "required_variants": ["Size"],
        "reject_if_no_variants": True,
        "max_per_run": 100,
    },
    "Necklaces": {
        "config_key": "collection_necklaces",
        "default_id": 0,
        "cj_category_ids": [
            "95D9F317-1DB3-4E42-A031-02223215B9C5",  # Necklace & Pendants
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100,
    },
    "Bracelets": {
        "config_key": "collection_bracelets",
        "default_id": 0,
        "cj_category_ids": [
            "0615F8DB-C10F-4BEF-892B-1C5B04268938",  # Bracelets & Bangles
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100,
    },
    "Earrings": {
        "config_key": "collection_earrings",
        "default_id": 0,
        "cj_category_ids": [
            "D28405AE-66C6-42E6-BFF0-D6FDCB5C083C",  # Earrings
            "D7CE9827-F50A-4B07-84BF-1BFE44188A1C",  # Fine Earrings
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100,
    },
    "Anklets": {
        "config_key": "collection_anklets",
        "default_id": 0,
        "cj_category_ids": [
            "2601070548141611900",  # Anklets
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 50,
    },
    "Piercings": {
        "config_key": "collection_piercings",
        "default_id": 0,
        "cj_category_ids": [
            "633E1860-7C63-4006-AB35-3FC16BECFA62",  # Body Jewelry
            "552F095A-904C-40E4-A43B-0CD1CE15D29F",  # 925 Silver Jewelry
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 50,
    },
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
    Search CJ by category IDs, score with jewelry_scoring, price with jewelry_pricing,
    rewrite names/descriptions with ARIA Haiku, then save.
    """
    from app.agents.cj_dropshipping import search_products, get_product_details
    from app.agents.store_config import get_config
    from app.agents.jewelry_scoring import score_jewelry_product
    from app.agents.jewelry_pricing import calculate_jewelry_price
    from app.agents.shipping_agent import get_best_shipping
    from app.agents.variant_normalizer import normalize_variants
    from app.agents.store_manager import add_product_to_store
    import json as _json

    collection_id = int(get_config(strategy["config_key"], default=str(strategy["default_id"])))
    max_products = strategy["max_per_run"]
    cj_category_ids = strategy.get("cj_category_ids", [])
    reject_if_no_variants = strategy.get("reject_if_no_variants", False)

    print(f"\n[Bulk Import] 🔍 {collection_name} — searching {len(cj_category_ids)} CJ categories")

    # ── PHASE 1: Fetch raw products ────────────────────────────
    all_raw_products = []
    per_category = max(5, max_products // max(len(cj_category_ids), 1))

    for cid in cj_category_ids:
        try:
            results = search_products(category_id=cid, limit=per_category) or []
            for p in results:
                sell_price = p.get("sellPrice", "0")
                cost = float(sell_price.split("-")[0].strip()) if isinstance(sell_price, str) and "-" in sell_price else float(sell_price or 0)
                if cost <= 0:
                    continue

                pid = p.get("pid", "")
                full = None
                try:
                    full = get_product_details(pid)
                except Exception as e:
                    print(f"[Bulk Import] ⚠ Full details failed for pid={pid}: {e}")

                # Images — always prefer productImageSet from full details
                all_images = []
                src = full or p
                image_set = src.get("productImageSet", [])
                if isinstance(image_set, list):
                    all_images = [img for img in image_set if img][:5]
                if not all_images:
                    main = src.get("productImage", "")
                    if main:
                        all_images = [main]
                product_image_set_count = len(image_set) if isinstance(image_set, list) else 0

                raw_variants = (full or p).get("variants", [])

                # Build extra text for metal/material detection across all fields
                variant_texts = []
                for v in raw_variants:
                    for vkey in ("variantName", "variantValue", "propertyName",
                                 "propertyValue", "variantSku", "variantNameEn", "name"):
                        val = v.get(vkey, "")
                        if val:
                            variant_texts.append(str(val))
                extra_text = " ".join(filter(None, [
                    p.get("categoryName", ""),
                    (full or p).get("productNameEn", ""),
                    (full or {}).get("description", ""),
                    " ".join(variant_texts),
                ]))

                all_raw_products.append({
                    "name": (full or p).get("productNameEn", p.get("productNameEn", "")),
                    "category": p.get("categoryName", collection_name),
                    "description": (full or {}).get("description", p.get("productNameEn", "")),
                    "image_url": all_images[0] if all_images else "",
                    "images": all_images,
                    "product_image_set_count": product_image_set_count,
                    "extra_text": extra_text,
                    "cost_price": cost,
                    "supplier_product_id": pid,
                    "supplier_name": "CJDropshipping",
                    "supplier_rating": float(p.get("productEval", 0) or 0),
                    "stock": 999,
                    "raw_variants": raw_variants,
                })
        except Exception as e:
            print(f"[Bulk Import] Search error category={cid}: {e}")

    # Deduplicate by pid
    seen_pids = set()
    unique = []
    for p in all_raw_products:
        pid = p["supplier_product_id"]
        if pid and pid not in seen_pids:
            seen_pids.add(pid)
            unique.append(p)
    unique = unique[:max_products]
    print(f"[Bulk Import] {len(unique)} unique products fetched for {collection_name}")

    # ── PHASE 2: Normalize variants + hard filter ──────────────
    scored_candidates = []
    hard_rejected = 0
    reject_log_count = 0

    for product in unique:
        raw_variants = product.pop("raw_variants", [])
        normalized = normalize_variants(raw_variants, collection_name)
        product["variants_normalized"] = normalized
        product["raw_variants_list"] = raw_variants

        # Ring size gate
        if reject_if_no_variants and not normalized["ring_size_valid"]:
            if reject_log_count < 10:
                reject_log_count += 1
                print(
                    f"[Bulk Import] ❌ REJECT #{reject_log_count} ring-size: '{product['name'][:50]}' | "
                    f"variant_groups={list(normalized['groups'].keys())} count={normalized['variant_count']}"
                )
            hard_rejected += 1
            continue

        # ── PHASE 3: Score ─────────────────────────────────────
        score_input = {**product, "images": product["images"]}
        score = score_jewelry_product(score_input)

        if score["rejected"]:
            if reject_log_count < 10:
                reject_log_count += 1
                img_count = max(len(product.get("images", [])), product.get("product_image_set_count", 0))
                print(
                    f"[Bulk Import] ❌ REJECT #{reject_log_count}: '{product['name'][:50]}'\n"
                    f"   reason={score['rejection_reason']} score={score['score']}\n"
                    f"   images={img_count} metal={score.get('detected_metal')} rating={product.get('supplier_rating')}"
                )
            hard_rejected += 1
            continue

        product["_score"] = score
        product["_needs_review"] = score["needs_review"]
        if score["needs_review"]:
            print(f"[Bulk Import] ⏸ Needs review ({score['score']}pt): {product['name'][:40]} — queuing for ARIA review")
        scored_candidates.append(product)

    print(f"[Bulk Import] {len(scored_candidates)} passed scoring for {collection_name}")

    if not scored_candidates:
        return {"collection": collection_name, "imported": 0, "rejected": hard_rejected}

    # ── PHASE 4: Batch rewrite names/descriptions ──────────────
    batch_size = 10
    rewrite_ready = []
    for i in range(0, len(scored_candidates), batch_size):
        batch = scored_candidates[i:i + batch_size]
        rewritten = batch_rewrite_products(batch, collection_name, collection_id)
        rewrite_ready.extend(rewritten)
        print(f"[Bulk Import] Rewrite batch {i // batch_size + 1}: {len(rewritten)}/{len(batch)} accepted")

    # ── PHASE 5: Price + ship + save ──────────────────────────
    imported = 0
    for product in rewrite_ready:
        try:
            score = product["_score"]
            raw_variants = product.get("raw_variants_list", [])
            normalized = product.get("variants_normalized", {})

            # Shipping — use first vid available
            vid = ""
            if raw_variants:
                vid = raw_variants[0].get("vid", "")
            shipping = get_best_shipping("CJDropshipping", vid)
            shipping_cost = shipping["cost"]
            shipping_days = shipping["days_max"]

            # Pricing
            pricing = calculate_jewelry_price(
                {**product, "supplier_name": "CJDropshipping"},
                score,
                shipping_cost=shipping_cost
            )

            # SKU
            cj_sku = ""
            if raw_variants:
                cj_sku = raw_variants[0].get("variantSku", "") or raw_variants[0].get("vid", "")

            product_data = {
                "name": product["mikisi_name"],
                "brand": "Mikisi",
                "category": product["category"],
                "description": product["mikisi_description"] or product["name"],
                "original_price": pricing["original_price"],
                "discount_percent": pricing["discount_percent"],
                "final_price": pricing["final_price"],
                "image_url": product["image_url"],
                "images": _json.dumps(product["images"]) if len(product.get("images", [])) > 1 else None,
                "stock": 999,
                "shipping_days": shipping_days,
                "supplier_name": "CJDropshipping",
                "supplier_url": "",
                "cj_product_id": product["supplier_product_id"],
                "cj_sku": cj_sku,
                "collection_id": collection_id,
                "variants": _json.dumps(raw_variants) if raw_variants else None,
            }

            p_obj, status = add_product_to_store(product_data)
            if status == "added":
                imported += 1
                signal_type = "PRODUCT_NEEDS_REVIEW" if product.get("_needs_review") else "PRODUCT_IMPORTED"
                try:
                    from app.agents.nervous_system import emit
                    emit(
                        signal_type=signal_type,
                        sender="bulk_import_agent",
                        payload={
                            "product_id": p_obj.id,
                            "name": product["mikisi_name"],
                            "collection_id": collection_id,
                            "store_price": pricing["final_price"],
                            "cost_price": product["cost_price"],
                            "quality_tier": score["quality_tier"],
                            "supplier": "CJDropshipping",
                        },
                        priority=5 if product.get("_needs_review") else 7
                    )
                except Exception as e:
                    print(f"[Bulk Import] Signal error: {e}")

        except Exception as e:
            print(f"[Bulk Import] Save error for {product.get('mikisi_name', '')}: {e}")

    total_rejected = hard_rejected + (len(scored_candidates) - len(rewrite_ready))
    print(f"[Bulk Import] ✅ {collection_name} — {imported} imported, {total_rejected} rejected")
    return {"collection": collection_name, "imported": imported, "rejected": total_rejected}


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