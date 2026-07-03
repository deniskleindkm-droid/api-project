import os
import json
import anthropic
from app.agents.store_config import get_config

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# COLLECTION MAPPING — 6 Jewelry Collections Only
# ============================================================

def get_collection_map():
    return {
        int(get_config("collection_rings", default="1")): {
            "name": "Rings",
            "keywords": ["ring", "band", "solitaire", "eternity ring", "engagement ring",
                        "wedding ring", "signet", "knuckle ring", "midi ring"]
        },
        int(get_config("collection_necklaces", default="2")): {
            "name": "Necklaces",
            "keywords": ["necklace", "pendant", "chain", "choker", "lariat", "collar",
                        "layered necklace", "neck chain", "pearl necklace"]
        },
        int(get_config("collection_bracelets", default="3")): {
            "name": "Bracelets",
            "keywords": ["bracelet", "bangle", "cuff", "charm bracelet", "tennis bracelet",
                        "chain bracelet", "wristlet", "arm chain"]
        },
        int(get_config("collection_earrings", default="4")): {
            "name": "Earrings",
            "keywords": ["earring", "stud", "hoop", "drop earring", "dangle",
                        "huggie", "ear cuff", "climber", "ear jacket", "threader"]
        },
        int(get_config("collection_anklets", default="5")): {
            "name": "Anklets",
            "keywords": ["anklet", "ankle bracelet", "ankle chain", "ankle jewelry", "foot jewelry"]
        },
        int(get_config("collection_piercings", default="6")): {
            "name": "Piercings & Body Jewelry",
            "keywords": ["nose ring", "nose stud", "nose hoop", "cartilage", "helix",
                        "tragus", "belly button ring", "navel ring", "body jewelry",
                        "piercing", "septum", "conch", "daith", "industrial bar"]
        },
    }


def assign_collection(product_name: str, product_category: str, product_description: str) -> int:
    """Assign product to correct jewelry collection based on keywords. Returns collection ID or None."""
    text = f"{product_name} {product_category} {product_description}".lower()
    collection_map = get_collection_map()

    scores = {}
    for col_id, col_data in collection_map.items():
        score = sum(1 for kw in col_data["keywords"] if kw in text)
        if score > 0:
            scores[col_id] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


def rewrite_product(cj_product: dict) -> dict:
    """
    ARIA rewrites a supplier product into Mikisi identity.
    Rejects anything that isn't quality jewelry.
    """
    raw_name = cj_product.get("name", "")
    raw_description = cj_product.get("description", "")
    raw_category = cj_product.get("category", "")
    price = cj_product.get("final_price", 0)

    brand_voice = get_config("brand_voice", default="Mikisi is elegant, empowering, intimate.")
    collection_id = assign_collection(raw_name, raw_category, raw_description)

    prompt = f"""You are ARIA, the intelligence behind Mikisi — a luxury jewelry brand for women who choose themselves.

A product is being imported. Your job is to:
1. Decide if this is quality jewelry that belongs in Mikisi — reject anything that isn't
2. Assign it to the correct collection
3. Rewrite the name — clean, elegant, maximum 8 words
4. Write an emotional description in Mikisi voice

BRAND VOICE:
{brand_voice}

OUR 6 COLLECTIONS — JEWELRY ONLY:
- Rings (ID: {get_config("collection_rings", "1")}) — all rings including engagement and stackable
- Necklaces (ID: {get_config("collection_necklaces", "2")}) — pendants, chains, chokers
- Bracelets (ID: {get_config("collection_bracelets", "3")}) — bangles, cuffs, charm bracelets
- Earrings (ID: {get_config("collection_earrings", "4")}) — studs, hoops, drops, ear cuffs
- Anklets (ID: {get_config("collection_anklets", "5")}) — ankle chains and bracelets
- Piercings & Body Jewelry (ID: {get_config("collection_piercings", "6")}) — nose rings, cartilage, body jewelry

PRODUCT FROM SUPPLIER:
Name: {raw_name[:200]}
Category: {raw_category}
Description: {raw_description[:300]}
Price: ${price}

REJECTION RULES — reject if any apply:
- Not jewelry (no skincare, makeup, hair, clothing, electronics, watches)
- Metal not specified or is plastic, acrylic, or resin
- Cheap alloy with no quality indicator

ACCEPTANCE RULES:
- Metal must be: 925 sterling silver, 18k gold plated, stainless steel, titanium, or surgical steel
- Name must be clean and elegant — no supplier language, no SEO stuffing
- Description makes a woman feel something — not a feature list

FINISH RULE — critical for multi-variant products:
- When a product has more than one finish option (e.g. gold + rhodium, gold + white gold), ALWAYS frame them as a customer choice: "in 18K gold or rhodium plating" / "your choice of gold or rhodium".
- NEVER write "with optional gold plating" — state both options directly.
- NEVER write both finishes as if simultaneously applied — never "rhodium-plated 18K gold". One piece has ONE finish; the customer chooses which.
- If only one finish exists, state it directly: "rhodium-plated 925 sterling silver".
- NEVER write "18K YellowGold" — always space it: "18K Yellow Gold".

DESCRIPTION TONE RULES — strictly enforced:
- 2-3 sentences. The description must include at least one concrete product detail (material, stone, closure, design feature, measurement).
- One emotional note is permitted but it must be earned by the product's actual qualities.
- BANNED phrases — never use any of these: "for the woman who", "unapologetically you", "unapologetically yours", "choose yourself", "you are the source", "permission to be", "be everything at once", "carries her own sunshine", "declare yourself", "effortlessly you", "quietly powerful" as a standalone closing, "your story", "on your terms", "knows her worth", "knows her own [noun]", "refuses to be understated", "in every hue", "writes her own story".
- End on the piece itself — not on the customer's aspirations.
- Concrete > abstract: "micro-set cubic zirconia" over "stones that catch light like intention".

Return JSON only:
{{
    "accepted": true or false,
    "rejection_reason": "why rejected if not accepted",
    "collection_id": the collection ID number,
    "collection_name": "collection name",
    "mikisi_name": "clean elegant product name max 8 words",
    "mikisi_description": "2-3 sentence description per the tone rules above",
    "confidence": 0.0 to 1.0
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
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

        collection_map = get_collection_map()
        if result.get("collection_id") not in collection_map:
            if collection_id:
                result["collection_id"] = collection_id
                result["collection_name"] = collection_map[collection_id]["name"]
            else:
                result["accepted"] = False
                result["rejection_reason"] = "Not a jewelry product — does not fit Mikisi's 6 collections"

        if result.get("confidence", 0) < 0.7:
            result["mikisi_name"] = raw_name[:60].strip()
            print(f"[Rewriter] Low confidence — keeping original name")

        print(f"[Rewriter] {'✅' if result.get('accepted') else '❌'} {raw_name[:50]} → {result.get('mikisi_name', 'rejected')}")
        return result

    except Exception as e:
        print(f"[Rewriter] Error: {e}")
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
