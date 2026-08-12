"""
Assigns "Shop by Style" / "Shop by Occasion" tags from a product's REAL
PHOTO, not its text description. Text-only tagging (the original approach
used to build the four demo collection pages) had a real, confirmed error
rate live -- e.g. earrings tagged "stud" from description text that were
actually hoops with dangling charms, since text rarely describes whether a
piece sits flush or hangs. A photo makes that trivial to see correctly, so
every NEW product import calls classify_style_from_photo() instead of
guessing from text.

STYLE_TAXONOMY only covers the four collections that have a real Style
hub live (Rings/Necklaces/Bracelets/Earrings) -- see _HUB_CONFIG in
docs/index.html, which this must be kept in sync with by hand if either
side's categories ever change. Anklets/Ear Cuffs/Jewelry Sets/Tennis
Bracelets (a name-based slice of Bracelets, not its own category) never
had a Style taxonomy and classify_style_from_photo() returns empty tags
for them on purpose.
"""
import os
import json
import base64
import requests
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STYLE_TAXONOMY = {
    "Rings": {
        "solitaire": "One stone set alone on a plain band, nothing else going on.",
        "open_adjustable": "Band has a visible open gap (not a closed circle) -- adjustable sizing is the visual signature.",
        "stacking": "Thin, simple band (or a multi-band set) clearly meant to be worn layered with others.",
        "statement": "Large, ornate, eye-catching design -- NOT delicate. Judge only the photo, never a marketing name.",
        "tennis": "A continuous line of same-size stones running all the way around the band (eternity-band style).",
        "vintage": "Antique-style filigree, ornate old-world detailing, aged/antique finish.",
        "signet": "Flat, wide top plate (seal shape), often with a monogram, letter, or symbol.",
    },
    "Necklaces": {
        "geometric": "Clean architectural shapes (bar, triangle, circle outline, square) -- not organic and not a specific symbol.",
        "symbolic": "A specific meaningful icon: heart, cross, clover, Star of David, religious/spiritual symbol, initial/letter.",
        "nature": "Depicts something from the natural world: flower, leaf, shell, butterfly, animal, celestial motif.",
        "statement": "Large, elaborate, eye-catching pendant/design. Judge only the photo, never a marketing name.",
        "solitaire": "Single stone pendant on a plain chain, nothing else going on.",
        "tassel_drop": "Hanging/draping movement -- tassels, chain fringe, multiple dangling elements.",
        "layered_beaded": "The chain itself is strung beads, or the piece is multiple strands meant to be layered.",
    },
    "Bracelets": {
        "tennis": "A continuous line of same-size stones all the way around the wrist.",
        "chain_link": "Visible chain-link construction is the main design (cuban, figaro, paperclip, curb) -- no dominant charms/stones.",
        "charm_station": "Charms or small stone stations spaced along an otherwise plain chain.",
        "beaded": "Made of strung beads.",
        "nature": "A nature-inspired charm/motif (leaf, flower, animal, shell) is the dominant design.",
        # "geometric" deliberately excluded -- tried during the manual build,
        # eliminated after a photo audit found it wrong 6 of 9 times (chain/
        # braided constructions mistagged as "geometric" from marketing copy).
    },
    "Earrings": {
        "hoop_huggie": "The earring's base hardware IS a hoop (open circle) or small hinged huggie loop, any size. If it also has a dangling charm, ALSO tag drop_dangle.",
        "drop_dangle": "Has a visible hanging/swinging element below the point of attachment -- on a stud, hook, OR hoop base.",
        "stud": "NO hoop, NO hanging movement -- sits flush against the earlobe, post/screw-back only. Be strict: any visible hoop shape or dangling element disqualifies this tag.",
        "tassel_threader": "Fine draping chain fringe, or a thin threader chain -- delicate movement distinct from a solid charm.",
    },
}

OCCASION_TAXONOMY = {
    "everyday": "Effortless, simple pieces for wherever the day takes you.",
    "polished": "For days you want everything to feel considered -- refined but not flashy.",
    "after_hours": "A little more sparkle after sunset -- eye-catching, dressier.",
    "occasion": "For moments worth dressing for -- special-occasion pieces.",
    "weekend": "Easy, casual pieces for slower days.",
}


def classify_style_from_photo(image_url: str, category: str) -> dict:
    """
    Looks at the product's real photo to assign style_tags/occasion.
    Returns {"style_tags": [...], "occasion": [...]} -- either list may be
    empty (genuinely no fit, or classification failed/skipped). Never
    raises -- an import must never fail because a style call had a bad day.
    """
    taxonomy = STYLE_TAXONOMY.get(category)
    if not taxonomy or not image_url:
        return {"style_tags": [], "occasion": []}

    try:
        img_resp = requests.get(image_url, timeout=15)
        img_resp.raise_for_status()
        img_b64 = base64.b64encode(img_resp.content).decode()
        media_type = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            media_type = "image/jpeg"
    except Exception as e:
        print(f"[StyleClassify] Could not fetch image for classification: {e}")
        return {"style_tags": [], "occasion": []}

    style_options = "\n".join(f"- {k}: {v}" for k, v in taxonomy.items())
    occasion_options = "\n".join(f"- {k}: {v}" for k, v in OCCASION_TAXONOMY.items())

    prompt = f"""Look at this real product photo of a piece of jewelry (category: {category}) and classify it.

STYLE (pick from exactly these keys, based ONLY on what you see in the photo -- never from a name or marketing copy):
{style_options}
A product can have MORE THAN ONE style tag if it genuinely fits more than one (e.g. a hoop earring with a dangling charm is both hoop_huggie and drop_dangle). Leave style_tags empty only if truly nothing fits.

OCCASION (pick 1-2 keys that fit the piece's overall mood):
{occasion_options}

Return ONLY this JSON, no other text, using the exact keys above:
{{"style_tags": ["..."], "occasion": ["..."]}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        valid_styles = set(taxonomy.keys())
        valid_occasions = set(OCCASION_TAXONOMY.keys())
        style_tags = [t for t in result.get("style_tags", []) if t in valid_styles]
        occasion = [t for t in result.get("occasion", []) if t in valid_occasions]
        return {"style_tags": style_tags, "occasion": occasion}
    except Exception as e:
        print(f"[StyleClassify] Classification failed for {category} product: {e}")
        return {"style_tags": [], "occasion": []}
