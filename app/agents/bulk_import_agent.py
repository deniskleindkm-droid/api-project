from dotenv import load_dotenv
load_dotenv()

import os
import json
import time
import anthropic
from datetime import datetime
from app.agents.store_config import get_config

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Categories where a ring with no size variants should show "One Size / Adjustable"
_RING_LIKE_CATEGORIES = {"Rings", "Bracelets", "Anklets"}


def _resolve_sizes(sizes_json: str, category: str) -> str:
    """
    Return sizes as-is if present.
    For ring-like categories with no size data, default to One Size / Adjustable
    so customers always see a size indicator on the product page.
    """
    if sizes_json:
        return sizes_json
    if category in _RING_LIKE_CATEGORIES:
        return json.dumps(["One Size / Adjustable"])
    return None


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
            "56B4F8B6-8600-4A18-913E-53F2F693EC2C",
            "FCE034F6-A2BF-47E3-852F-FA9F67F904B2"
        ],
        "required_variants": ["Size"],
        "reject_if_no_variants": False,
        "max_per_run": 100
    },
    "Necklaces": {
        "config_key": "collection_necklaces",
        "default_id": 0,
        "cj_category_ids": [
            "95D9F317-1DB3-4E42-A031-02223215B9C5"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100
    },
    "Bracelets": {
        "config_key": "collection_bracelets",
        "default_id": 0,
        "cj_category_ids": [
            "0615F8DB-C10F-4BEF-892B-1C5B04268938"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100
    },
    "Earrings": {
        "config_key": "collection_earrings",
        "default_id": 0,
        "cj_category_ids": [
            "D28405AE-66C6-42E6-BFF0-D6FDCB5C083C",
            "D7CE9827-F50A-4B07-84BF-1BFE44188A1C"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 100
    },
    "Anklets": {
        "config_key": "collection_anklets",
        "default_id": 0,
        "cj_category_ids": [
            "2601070548141611900",
            "552F095A-904C-40E4-A43B-0CD1CE15D29F"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 50
    },
    "Ear Cuffs": {
        "config_key": "collection_ear_cuffs",
        "default_id": 0,
        "cj_category_ids": [
            "D28405AE-66C6-42E6-BFF0-D6FDCB5C083C",
            "633E1860-7C63-4006-AB35-3FC16BECFA62"
        ],
        "keywords": [
            "ear cuff no piercing",
            "925 silver ear cuff",
            "gold ear cuff women",
            "cartilage ear cuff"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 50
    },
    "Jewelry Sets": {
        "config_key": "collection_jewelry_sets",
        "default_id": 0,
        "cj_category_ids": [
            "552F095A-904C-40E4-A43B-0CD1CE15D29F"
        ],
        "keywords": [
            "925 silver jewelry set necklace earring",
            "gold plated jewelry set women",
            "matching necklace bracelet set",
            "jewelry gift set women sterling"
        ],
        "required_variants": [],
        "reject_if_no_variants": False,
        "max_per_run": 50
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

    # Include actual material and raw name so ARIA works with real data
    # Truncate names to 80 chars to keep prompt within token budget
    product_list = "\n".join([
        f"{i+1}. Raw name: {p.get('name', '')[:80]} | Material: {p.get('material', 'not specified')} | Colors available: {p.get('colors', 'not specified')} | Collection: {collection_name}"
        for i, p in enumerate(products)
    ])

    prompt = f"""You are ARIA, the intelligence behind Mikisi — a luxury jewelry brand for women who choose themselves.

BRAND VOICE:
{brand_voice}

INTENDED COLLECTION: {collection_name}

Products below are from Silverbene. Accept all jewelry. For each product do exactly four things:

1. VERIFY COLLECTION — look at the actual product name and decide which Mikisi collection it truly belongs to: Rings, Necklaces, Bracelets, Earrings, Anklets, Ear Cuffs, or Jewelry Sets. Do not blindly use the intended collection — correct it if wrong. An earring found in a Rings search should be corrected to Earrings.

2. CLEAN THE NAME — strip supplier jargon, model codes, "women", "for her", "S925", sizes. Max 6 words. Keep the essence.

3. IDENTIFY MATERIAL — read raw name and material field. Write exactly what it is: "925 Sterling Silver", "18k Gold Plated 925 Silver", "Rhodium Plated", etc. This shows on the product page — be accurate.

4. WRITE MIKISI DESCRIPTION — exactly 2 sentences. Intimate, empowering, elegant. Mention the actual material in the first sentence.

PRODUCTS:
{product_list}

Return ONLY a JSON array with {len(products)} objects in the same order:
[
  {{
    "index": 1,
    "accepted": true,
    "correct_collection": "Rings",
    "mikisi_name": "Twisted Band Open Ring",
    "mikisi_material": "925 Sterling Silver",
    "mikisi_description": "Forged in 925 sterling silver, this ring moves with you through every version of yourself. Open-ended by design — because you are never finished becoming.",
    "rejection_reason": null
  }}
]

Return ONLY valid JSON array. No other text."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        if not message.content or message.content[0] is None:
            raise ValueError("Empty API response")

        text = message.content[0].text
        if not text:
            raise ValueError("No text in API response")
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.lower().startswith("json"):
                    text = text[4:]
        text = text.strip()

        # Find JSON array boundaries in case there's stray text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start:end + 1]

        results = json.loads(text)
        if not isinstance(results, list):
            raise ValueError(f"Expected JSON array, got {type(results)}")

        # Collection name → ID lookup for ARIA's corrections
        _collection_map = {
            "Rings": "collection_rings",
            "Necklaces": "collection_necklaces",
            "Bracelets": "collection_bracelets",
            "Earrings": "collection_earrings",
            "Anklets": "collection_anklets",
            "Ear Cuffs": "collection_ear_cuffs",
            "Jewelry Sets": "collection_jewelry_sets",
        }

        # Merge rewrite results — all accepted, capture material + corrected collection
        rewritten = []
        for i, result in enumerate(results):
            if i >= len(products):
                break
            if not isinstance(result, dict):
                # null or unexpected — fall back to raw for this item
                product = products[i].copy()
                product["mikisi_name"] = product.get("name", "")[:100]
                product["mikisi_description"] = ""
                product["accepted"] = True
                rewritten.append(product)
                continue

            product = products[i].copy()
            product["mikisi_name"] = (result.get("mikisi_name") or product.get("name", ""))[:100]
            product["mikisi_description"] = result.get("mikisi_description", "")
            product["material"] = result.get("mikisi_material") or product.get("material", "")

            # If ARIA identified a different collection, look up its ID
            aria_collection = (result.get("correct_collection") or "").strip()
            if aria_collection and aria_collection != collection_name and aria_collection in _collection_map:
                from app.agents.store_config import get_config as _gc
                corrected_id = int(_gc(_collection_map[aria_collection], default="0") or 0)
                if corrected_id:
                    product["_corrected_collection_id"] = corrected_id
                    print(f"[Bulk Import] ARIA corrected '{product['mikisi_name'][:40]}' -> {aria_collection} (ID {corrected_id})")

            product["accepted"] = True
            rewritten.append(product)

        return rewritten

    except Exception as e:
        import traceback
        print(f"[Bulk Import] Batch rewrite error: {e}")
        traceback.print_exc()
        # On error — preserve products with raw names, don't lose them
        return [{**p, "mikisi_name": p.get("name", "")[:100],
                 "mikisi_description": "", "accepted": True} for p in products]


# ============================================================
# SEARCH AND IMPORT PER COLLECTION
# ============================================================

def import_for_collection(collection_name: str, strategy: dict) -> dict:
    """
    Search Silverbene by collection keywords, score, price, rewrite, then save.
    CJ Dropshipping is disabled — all imports come from Silverbene.
    """
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    from app.agents.store_config import get_config
    silverbene = SilverbeneAdapter()
    from app.agents.jewelry_pricing import calculate_mikisi_price, detect_material
    from app.agents.variant_normalizer import normalize_variants
    from app.agents.store_manager import add_product_to_store
    import json as _json

    collection_id = int(get_config(strategy["config_key"], default=str(strategy["default_id"])))
    max_products = strategy["max_per_run"]
    reject_if_no_variants = strategy.get("reject_if_no_variants", False)

    print(f"\n[Bulk Import] 🔍 {collection_name} — searching Silverbene catalog")

    # ── PHASE 1: Fetch from Silverbene ────────────────────────────
    raw_results = silverbene.search_by_category(collection_name, limit=max_products)
    print(f"[Bulk Import] Silverbene returned {len(raw_results)} raw products for {collection_name}")

    all_raw_products = []
    for p in raw_results:
        if not p.get("cost_price", 0):
            continue
        images = p.get("images", [])
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except Exception:
                images = [images] if images else []
        image_url = p.get("image_url", images[0] if images else "")

        extra_text = " ".join(filter(None, [
            p.get("name", ""),
            p.get("description", ""),
            p.get("material", ""),
            p.get("material_raw", ""),
        ]))

        all_raw_products.append({
            "name": p.get("name", ""),
            "category": collection_name,
            "description": p.get("description", ""),
            "image_url": image_url,
            "images": images,
            "product_image_set_count": len(images),
            "extra_text": extra_text,
            "material_name_en_set": [p.get("material", "")] if p.get("material") else [],
            "cost_price": p.get("cost_price", 0),
            "supplier_product_id": p.get("supplier_product_id", ""),
            "supplier_name": "Silverbene",
            "supplier_rating": p.get("supplier_rating", 5.0),
            "stock": p.get("stock", 999),
            "raw_variants": p.get("variants", []),
            # Silverbene-specific structured fields
            "material": p.get("material", ""),
            "sizes": p.get("sizes"),
            "colors": p.get("colors"),
        })

    # Deduplicate by supplier_product_id
    seen_ids = set()
    unique = []
    for p in all_raw_products:
        sid = p["supplier_product_id"]
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            unique.append(p)
    unique = unique[:max_products]
    print(f"[Bulk Import] {len(unique)} unique products fetched from Silverbene for {collection_name}")

    # ── PHASE 2 & 3: Silverbene pass-through ──────────────────
    # Silverbene is a vetted fine jewelry supplier — all products are accepted.
    # No hard scoring rejections. Only skip products with no price or no images.
    scored_candidates = []
    hard_rejected = 0
    rejection_details = []

    for product in unique:
        raw_variants = product.pop("raw_variants", [])
        product["raw_variants_list"] = raw_variants

        if not product.get("cost_price", 0):
            hard_rejected += 1
            continue
        if not product.get("images") and not product.get("image_url"):
            hard_rejected += 1
            continue

        # Assign a standard score so pricing/tier logic works downstream
        product["_score"] = {
            "score": 75,
            "auto_import": True,
            "needs_review": False,
            "rejected": False,
            "rejection_reason": None,
            "quality_tier": "luxury",
            "detected_metal": product.get("material", "925_silver"),
            "detected_stone": None,
            "dimensions": {},
        }
        product["_needs_review"] = False
        scored_candidates.append(product)

    print(f"[Bulk Import] {len(scored_candidates)} products from Silverbene ready for rewrite")

    if not scored_candidates:
        return {"collection": collection_name, "imported": 0, "rejected": hard_rejected, "rejection_details": rejection_details}

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
            raw_variants = product.get("raw_variants_list", [])
            cost_price = float(product["cost_price"])

            # Detect material from raw options + name for accurate pricing
            material_key = detect_material(
                product.get("name", ""),
                product.get("_options", raw_variants)
            )

            # Pricing
            pricing = calculate_mikisi_price(cost_price, material_key)

            # Flags
            is_premium    = material_key == "moissanite"
            needs_review  = cost_price > 40

            # SKU — Silverbene options have option_id, not variantSku
            cj_sku = ""
            if raw_variants and isinstance(raw_variants, list):
                first = raw_variants[0]
                cj_sku = str(first.get("option_id", "")) or str(first.get("sku", ""))

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
                "stock": product.get("stock", 999),
                "shipping_days": 14,
                "supplier_name": "Silverbene",
                "supplier_url": "",
                "cj_product_id": product["supplier_product_id"],
                "cj_sku": cj_sku,
                "collection_id": product.get("_corrected_collection_id", collection_id),
                "variants": _json.dumps(raw_variants) if raw_variants else None,
                # Silverbene display fields
                "material": product.get("material") or "",
                "sizes": _resolve_sizes(product.get("sizes"), product.get("category", "")),
                "colors": product.get("colors"),
                # Pricing internals
                "silverbene_cost": cost_price,
                "markup_used":     pricing["markup_used"],
                "shipping_cost":   pricing["shipping_cost"],
                # Flags
                "is_premium":   is_premium,
                "needs_review": needs_review,
            }

            p_obj, status = add_product_to_store(product_data)
            if status in ("added", "price_updated"):
                imported += 1
                signal_type = "PRODUCT_NEEDS_REVIEW" if needs_review else "PRODUCT_IMPORTED"
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
                            "cost_price": cost_price,
                            "material": material_key,
                            "supplier": "Silverbene",
                        },
                        priority=5 if needs_review else 7
                    )
                except Exception as e:
                    print(f"[Bulk Import] Signal error: {e}")

        except Exception as e:
            print(f"[Bulk Import] Save error for {product.get('mikisi_name', '')}: {e}")

    total_rejected = hard_rejected + (len(scored_candidates) - len(rewrite_ready))
    print(f"[Bulk Import] ✅ {collection_name} — {imported} imported, {total_rejected} skipped")

    # ARIA notes what was added to each collection
    try:
        from app.agents.aria_memory import store_episode
        store_episode(
            event=f"Silverbene import: {collection_name}",
            context=f"{imported} products added to {collection_name} collection",
            decision=f"Imported {imported} Silverbene products with material and Mikisi descriptions",
            outcome="collection_updated" if imported > 0 else "no_new_products",
            significance="medium"
        )
        print(f"[ARIA] 📦 {collection_name}: {imported} new products stored in memory")
    except Exception as e:
        print(f"[Bulk Import] ARIA memory note error: {e}")

    return {"collection": collection_name, "imported": imported, "rejected": total_rejected, "rejection_details": rejection_details}


# ============================================================
# MAIN BULK IMPORT AGENT
# Runs every 24 hours from scheduler
# ============================================================

def run_bulk_import_agent(max_per_collection: int = None):
    """
    Main bulk import loop.
    Searches CJ for each of our 6 collections.
    Batch rewrites with ARIA using Haiku (cheap).
    Imports accepted products with Mikisi identity.
    """
    print(f"\n[Bulk Import] 🚀 Starting bulk import — {datetime.utcnow()}")

    # Write start event — command center tracks this
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="bulk_import_agent",
                memory_type="run_started",
                content=json.dumps({"timestamp": datetime.utcnow().isoformat(), "status": "running"}),
                confidence=0.9
            ))
            session.commit()
    except Exception:
        pass

    results = []
    total_imported = 0
    total_rejected = 0

    for collection_name, strategy in COLLECTION_STRATEGIES.items():
        try:
            strat = {**strategy}
            if max_per_collection is not None:
                strat["max_per_run"] = max_per_collection
            result = import_for_collection(collection_name, strat)
            results.append(result)
            total_imported += result.get("imported", 0)
            total_rejected += result.get("rejected", 0)
        except Exception as e:
            print(f"[Bulk Import] Error on {collection_name}: {e}")
            results.append({"collection": collection_name, "imported": 0, "error": str(e)})

    print(f"\n[Bulk Import] ✅ Complete — {total_imported} imported, {total_rejected} rejected")
    print(f"[Bulk Import] Summary: {results}")

    # Save to memory
    # Save run to memory
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

    # Emit import complete signal to nervous system
    try:
        from app.agents.nervous_system import emit
        emit(
            signal_type="BULK_IMPORT_COMPLETE",
            sender="bulk_import_agent",
            payload={"total_imported": total_imported, "total_rejected": total_rejected, "collections": len(results)},
            priority=6
        )
    except Exception as e:
        print(f"[Bulk Import] Signal error: {e}")

    # ARIA reports to Dennis after every import run
    try:
        from app.agents.aria_intelligence import aria_think
        from app.agents.email_partner import send_email
        from app.agents.aria_memory import store_episode
        import os

        collection_summary = " | ".join([
            f"{r['collection']}: {r.get('imported', 0)} imported"
            for r in results
        ])

        situation = (
            f"Silverbene bulk import just completed. "
            f"Total imported: {total_imported} products across {len(results)} collections. "
            f"Breakdown: {collection_summary}. "
            f"Dennis needs a brief report on what was added to Mikisi's store."
        )

        aria_result = aria_think(situation=situation, urgency="medium")
        store_episode(
            event=f"Silverbene import: {total_imported} products imported",
            context=collection_summary,
            decision="ARIA reported import results to Dennis",
            outcome="import_complete",
            significance="high"
        )

        dennis_email = os.getenv("DENNIS_EMAIL")
        if dennis_email and aria_result:
            email_data = aria_result.get("email_to_dennis", {})
            subject = email_data.get("subject", f"Mikisi Import Complete — {total_imported} New Products Added")
            body = email_data.get("body", "")
            if body:
                send_email(dennis_email, subject, body, is_html=True)
                print(f"[Bulk Import] ✅ ARIA import report sent to Dennis")

    except Exception as e:
        print(f"[Bulk Import] ARIA reporting error: {e}")

    return {
        "total_imported": total_imported,
        "total_rejected": total_rejected,
        "results": results
    }