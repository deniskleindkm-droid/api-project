import os
import json
import anthropic
from app.agents.store_config import get_config

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# COLLECTION MAPPING
# ARIA uses this to assign correct collection
# Keys are keywords ARIA looks for in product name/category
# ============================================================

def get_collection_map():
    return {
        int(get_config("collection_jewelry", default="13")): {
            "name": "Jewelry",
            "keywords": ["ring", "necklace", "bracelet", "anklet", "piercing", "nose ring",
                        "earring", "pendant", "chain", "choker", "bangle", "jewelry", "jewel",
                        "sterling silver", "gold plated", "crystal", "gemstone", "zircon"]
        },
        int(get_config("collection_watches", default="14")): {
            "name": "Women Watches",
            "keywords": ["watch", "timepiece", "wristwatch", "chronograph", "quartz clock"]
        },
        int(get_config("collection_hair_accessories", default="15")): {
            "name": "Hair Accessories",
            "keywords": ["hair clip", "claw clip", "hair pin", "barrette", "scrunchie",
                        "hair tie", "headband", "hair band", "bobby pin", "hair accessory",
                        "ponytail", "hair grip", "hair comb", "hair slide"]
        },
        int(get_config("collection_makeup", default="16")): {
            "name": "Makeup Accessories",
            "keywords": ["makeup brush", "beauty blender", "sponge", "foundation brush",
                        "eyelash", "false lash", "lip brush", "contour", "highlighter brush",
                        "makeup tool", "cosmetic brush", "blush brush", "powder puff",
                        "makeup bag", "beauty tool", "makeup applicator"]
        },
        int(get_config("collection_skincare", default="17")): {
            "name": "Skincare & Facial Tools",
            "keywords": ["facial roller", "jade roller", "gua sha", "face mask", "serum",
                        "moisturizer", "cleanser", "toner", "eye cream", "face wash",
                        "skincare", "skin care", "facial", "derma", "collagen", "retinol",
                        "vitamin c", "hyaluronic", "face tool", "microneedle", "face lift",
                        "led mask", "face massager", "beauty device", "blackhead"]
        },
        int(get_config("collection_nail_care", default="18")): {
            "name": "Nail Care",
            "keywords": ["nail", "cuticle", "nail file", "nail art", "nail polish",
                        "nail tool", "manicure", "pedicure", "nail gel", "nail lamp",
                        "nail brush", "nail sticker", "nail extension", "nail drill"]
        }
    }


def assign_collection(product_name: str, product_category: str, product_description: str) -> int:
    """
    Assign product to correct collection based on keywords.
    Returns collection ID or None if no match.
    """
    text = f"{product_name} {product_category} {product_description}".lower()
    collection_map = get_collection_map()

    scores = {}
    for col_id, col_data in collection_map.items():
        score = sum(1 for kw in col_data["keywords"] if kw in text)
        if score > 0:
            scores[col_id] = score

    if not scores:
        return None

    # Return collection with highest keyword match
    return max(scores, key=scores.get)


def rewrite_product(cj_product: dict) -> dict:
    """
    ARIA rewrites CJ product into Mikisi identity.
    - Clean elegant name
    - Emotional description in Mikisi voice
    - Correct collection assignment
    - Quality check — reject if doesn't fit
    """
    raw_name = cj_product.get("name", "")
    raw_description = cj_product.get("description", "")
    raw_category = cj_product.get("category", "")
    price = cj_product.get("final_price", 0)

    brand_voice = get_config("brand_voice", default="Mikisi is elegant, empowering, intimate.")

    # First try keyword-based collection assignment
    collection_id = assign_collection(raw_name, raw_category, raw_description)

    prompt = f"""You are ARIA, the intelligence behind Mikisi — a premium women's beauty accessories store.

A product is being imported from a supplier. Your job is to:
1. Decide if this product belongs in Mikisi — reject anything that doesn't fit our 6 collections
2. Assign it to the correct collection
3. Rewrite the name — clean, elegant, maximum 8 words
4. Write an emotional description in Mikisi voice

BRAND VOICE:
{brand_voice}

OUR 6 COLLECTIONS ONLY:
- Jewelry (ID: {get_config("collection_jewelry", "13")}) — rings, necklaces, earrings, piercings, bracelets
- Women Watches (ID: {get_config("collection_watches", "14")}) — quality timepieces
- Hair Accessories (ID: {get_config("collection_hair_accessories", "15")}) — clips, pins, scrunchies, headbands
- Makeup Accessories (ID: {get_config("collection_makeup", "16")}) — brushes, sponges, tools
- Skincare & Facial Tools (ID: {get_config("collection_skincare", "17")}) — serums, masks, rollers, devices
- Nail Care (ID: {get_config("collection_nail_care", "18")}) — nail tools, art, manicure

PRODUCT FROM SUPPLIER:
Name: {raw_name[:200]}
Category: {raw_category}
Description: {raw_description[:300]}
Price: ${price}

RULES:
- If product doesn't fit any of our 6 collections → reject it
- No clothing, no shoes, no food, no electronics unrelated to beauty
- Jewelry must be sterling silver or gold plated quality — no cheap plastic
- Name must be clean and elegant — no Chinese supplier language, no SEO stuffing
- Description must make a woman feel something — not list features

Return JSON only:
{{
    "accepted": true or false,
    "rejection_reason": "why rejected if not accepted",
    "collection_id": the collection ID number,
    "collection_name": "collection name",
    "mikisi_name": "clean elegant product name max 8 words",
    "mikisi_description": "emotional 2-3 sentence description in Mikisi voice",
    "confidence": 0.0 to 1.0
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        result = json.loads(text.strip())

        # Validate collection ID is one of our 6
        collection_map = get_collection_map()
        if result.get("collection_id") not in collection_map:
            # Fall back to keyword match
            if collection_id:
                result["collection_id"] = collection_id
                result["collection_name"] = collection_map[collection_id]["name"]
            else:
                result["accepted"] = False
                result["rejection_reason"] = "Collection not in Mikisi's 6 locked collections"

        print(f"[Rewriter] {'✅' if result.get('accepted') else '❌'} {raw_name[:50]} → {result.get('mikisi_name', 'rejected')}")
        return result

    except Exception as e:
        print(f"[Rewriter] Error: {e}")
        # Fall back to keyword match if ARIA fails
        if collection_id:
            return {
                "accepted": True,
                "collection_id": collection_id,
                "collection_name": get_collection_map()[collection_id]["name"],
                "mikisi_name": raw_name[:60],
                "mikisi_description": raw_description[:200],
                "confidence": 0.5
            }
        return {"accepted": False, "rejection_reason": f"Rewriter error: {e}"}