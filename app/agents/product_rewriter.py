import os
import json
import re
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
- When a product has more than one finish option (e.g. gold + rhodium, gold + white gold), ALWAYS frame them as "available in [finish A] or [finish B]" — e.g. "available in polished silver or an 18K gold-plated finish". This exact "available in ___" construction is the required phrasing, not just an example. THREE OR MORE options: list every one of them, never just two — "available in [A], [B], or [C]".
- NEVER write "with optional gold plating" — state both options directly.
- NEVER write both finishes as if simultaneously applied — never "rhodium-plated 18K gold". One piece has ONE finish; the customer chooses which.
- If only one finish exists, state it directly using the same construction: "available in rhodium-plated 925 sterling silver".
- Every mention of ANY plated finish MUST say "-plated" or "plating" — silver (925 sterling silver) is the only SOLID metal this catalog sells; every other finish word (gold, rose gold, white gold, rhodium, black rhodium, or any other plating color) is always a plating over base metal, never solid, and writing it bare reads as solid to a customer. This applies to every finish color, not just gold — "Rose Gold" must say "Rose Gold-plated", "Black Rhodium" must say "Black Rhodium-plated", etc. Only "silver" itself is ever stated bare.
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

        # Guardrail: the LLM can assign the right collection_id and still
        # write a mikisi_name whose own trailing word implies a different
        # item type — self-inconsistent within the same response (e.g.
        # collection_id=Necklaces, mikisi_name="...Station Chain Ring").
        # Nothing else catches this since collection_id and mikisi_name are
        # never otherwise cross-checked. implied_category_from_name is the
        # same function catalog_audit_agent.py's name/category check uses,
        # so detection and prevention can never drift out of agreement.
        from app.agents.catalog_audit_agent import implied_category_from_name
        implied = implied_category_from_name(result.get("mikisi_name", ""))
        result_collection = collection_map.get(result.get("collection_id"), {}).get("name")
        if implied and result_collection and implied != result_collection:
            print(f"[Rewriter] mikisi_name implies {implied} but collection is {result_collection} — keeping original name")
            result["mikisi_name"] = raw_name[:60].strip()

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


_FINISH_BANNED_PHRASES = [
    "for the woman who", "unapologetically you", "unapologetically yours",
    "choose yourself", "you are the source", "permission to be",
    "be everything at once", "carries her own sunshine", "declare yourself",
    "effortlessly you", "your story", "on your terms", "knows her worth",
    "refuses to be understated", "in every hue", "writes her own story",
]


def build_finish_clause(colors: list) -> str | None:
    """
    Deterministic — NO LLM. The single source of truth for what a product's
    finish clause should say, computed directly from its real color/variant
    data. Returns None when there's no genuine metal-finish choice at all
    (e.g. colors describing a gemstone/certificate, not a plating) — silver
    is the only solid metal this catalog sells, everything else is a
    plating, but a product can also have ZERO real finish choice (single
    material, no alternative), which must never be dressed up as a choice.

    Built after fix_finish_wording()'s first version let an LLM freely
    decide both WHICH finishes exist and how to word them — it fabricated
    a "silver or 18K gold-plated" choice on a Moissanite ring that only
    ever had one material (colors=["Moissanite · 9 Stones · with GRA
    Certificate"] — a gemstone/certificate descriptor, not a finish at
    all), and separately under-counted a real 3-finish ring (Rose/Yellow/
    White Gold) down to just two. Confirmed live, both cases, 2026-07-25.
    Grounding the actual finish list here, and only ever handing the LLM
    an exact pre-computed phrase to place (see fix_finish_wording below),
    removes that failure mode entirely — the LLM can no longer invent or
    drop an option, only decide where a fixed sentence goes.
    """
    # Order matters -- more specific named colors must be checked before the
    # generic yellow/bare-gold fallback. Every named color keeps its own
    # qualifier (rose/white/champagne) for consistency -- a product with
    # colors ["Rose Gold", "Yellow Gold", "White Gold"] must read "rose
    # gold-plated, yellow gold-plated, or white gold-plated", never drop a
    # name to a generic label while others stay named (confirmed live as
    # confusing -- Dennis 2026-07-25: "which is which?" on product #578).
    # "Champagne Gold" is its own real, distinct color at Silverbene (seen
    # live alongside "18K Yellow" and "14K Gold" as separate options on the
    # same product, #739) -- it must never collapse into generic yellow gold.
    named_patterns = [
        (re.compile(r'rose\s*gold', re.I), 'rose gold-plated'),
        (re.compile(r'white\s*gold', re.I), 'white gold-plated'),
        (re.compile(r'champagne\s*gold', re.I), 'champagne gold-plated'),
        (re.compile(r'black\s*rhodium', re.I), 'black rhodium-plated'),
        (re.compile(r'\brhodium\b', re.I), 'rhodium-plated'),
        (re.compile(r'\bplatinum\b', re.I), 'platinum-plated'),
        (re.compile(r'\bsilver\b', re.I), 'silver'),
    ]
    # Yellow/bare gold, checked only when none of the above matched --
    # PRESERVES the real karat when Silverbene's own data specifies one
    # (e.g. "14K Yellow Gold" -> "14K gold-plated") instead of always
    # defaulting to a generic label. Confirmed live: some products are
    # genuinely 14K-only (no 18K alternative exists for them at all --
    # products #596, #968, #823), so claiming a karat we don't know, OR
    # silently dropping a karat we DO know, are both real accuracy losses
    # (Dennis 2026-07-25, product #596 Starfish Pearl Drop Earrings: chip
    # said "14K Yellow Gold", description said generic "yellow gold-plated"
    # with no karat at all). Also matches "18K Yellow" with no "Gold" word
    # at all (seen live on #739) -- karat + "Yellow" implies gold in this
    # catalog even when the word itself is dropped.
    karat_re = re.compile(r'\b(\d{1,2})K\b', re.I)
    # Bare "yellow" alone is NOT enough to imply gold -- confirmed live, a
    # stone-color entry like "Yellow CZ" or "Yellow Jade" would otherwise be
    # misread as a yellow-gold finish claim (product #863). Only a literal
    # "gold" word, or a karat number directly attached to "Yellow" (matching
    # Silverbene's own abbreviated "18K Yellow" shorthand, seen live on
    # product #739 with no "Gold" word at all), counts as gold.
    yellow_or_gold_re = re.compile(r'\bgold\b|\b\d{1,2}K\s*Yellow\b', re.I)

    finishes = []
    for c in colors or []:
        for part in str(c).split('·'):
            part = part.strip()
            matched = False
            for pattern, label in named_patterns:
                if pattern.search(part):
                    if label not in finishes:
                        finishes.append(label)
                    matched = True
                    break
            if matched:
                continue
            if yellow_or_gold_re.search(part):
                km = karat_re.search(part)
                label = f"{km.group(1)}K gold-plated" if km else "yellow gold-plated"
                if label not in finishes:
                    finishes.append(label)
    if not finishes:
        return None
    if len(finishes) == 1:
        return f"available in {finishes[0]}"
    if len(finishes) == 2:
        return f"available in {finishes[0]} or {finishes[1]}"
    return "available in " + ", ".join(finishes[:-1]) + f", or {finishes[-1]}"


def fix_finish_wording(description: str, colors_json: str) -> str | None:
    """
    Narrow, targeted rewrite for EXISTING product descriptions — corrects
    only the finish/material sentence, using build_finish_clause() above as
    the exact, non-negotiable ground truth for what it must say. The LLM's
    only job here is placement/grammar (fit the exact phrase naturally into
    the existing sentence, or remove an existing false claim if there's no
    real finish choice) — never deciding what the finish options are.

    Deliberately does NOT touch the emotional/brand-voice sentence, name,
    or collection — only the finish clause, so this is safe to run against
    the live catalog without the risk full rewrite_product() would carry
    (re-scoring/re-collection-assigning/renaming products that already
    have real order history and live product pages).

    Returns the corrected description, or None if nothing changed / on
    error (caller should skip saving in that case).
    """
    try:
        colors = json.loads(colors_json) if colors_json else []
    except Exception:
        colors = []

    clause = build_finish_clause(colors)
    if clause:
        instruction = (
            f'The description must state the finish EXACTLY as: "{clause}" — '
            f'use this exact phrase verbatim, do not reword it. Fix the sentence '
            f'containing the finish mention to use this exact phrase naturally; '
            f'leave every other word unchanged.'
        )
    else:
        instruction = (
            'This product has no real metal finish choice (the color/variant data '
            'describes something else, e.g. a gemstone or certificate — not a '
            'metal plating). Remove any claim of a finish/plating choice from the '
            'description entirely — do not invent one. Leave every other word unchanged.'
        )

    prompt = f"""Fix ONLY the finish/material sentence in this jewelry description.

{instruction}

Do not introduce any of these banned phrases: {", ".join(f'"{p}"' for p in _FINISH_BANNED_PHRASES)}.

Current description: {description}

Return ONLY valid JSON, no other text: {{"description": "corrected description"}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
        if m:
            text = m.group(1)
        else:
            m2 = re.search(r'(\{.*\})', text, re.S)
            if m2:
                text = m2.group(1)
        result = json.loads(text)
        new_desc = result.get("description", "").strip()
        if not new_desc or any(p in new_desc.lower() for p in _FINISH_BANNED_PHRASES):
            return None
        return new_desc
    except Exception as e:
        print(f"[Rewriter] fix_finish_wording error: {e}")
        return None
