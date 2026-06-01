"""
Jewelry scoring engine — 6-dimension, 100-point scale.
Hard rejection filters run first; any fail = immediate reject.
"""


def score_jewelry_product(product: dict) -> dict:
    name = product.get("name", "")
    description = product.get("description", "")
    images = product.get("images", [])
    image_url = product.get("image_url", "")
    supplier_rating = float(product.get("supplier_rating", 0.0))

    text = f"{name} {description}".lower()

    def _reject(reason, metal=None, stone=None):
        return {
            "score": 0, "auto_import": False, "needs_review": False, "rejected": True,
            "rejection_reason": reason, "quality_tier": None,
            "detected_metal": metal, "detected_stone": stone,
            "dimensions": {}
        }

    # ── Image count ────────────────────────────────────────────
    image_count = 0
    if isinstance(images, list):
        image_count = len(images)
    elif isinstance(images, str) and images:
        try:
            import json
            image_count = len(json.loads(images))
        except Exception:
            image_count = 1 if image_url else 0
    elif image_url:
        image_count = 1

    if image_count < 3:
        return _reject(f"Only {image_count} image(s) — minimum 3 required")

    # ── Supplier rating ────────────────────────────────────────
    if supplier_rating > 0 and supplier_rating < 4.0:
        return _reject(f"Supplier rating {supplier_rating:.1f} below minimum 4.0")

    # ── Bad materials ──────────────────────────────────────────
    for bad in ["plastic", "acrylic", "resin", "rubber"]:
        if bad in text:
            return _reject(f"Forbidden material detected: '{bad}'")

    # ── METAL PURITY (30 pts) ──────────────────────────────────
    metal_score = 0
    detected_metal = None

    if "925" in text or "sterling silver" in text:
        metal_score, detected_metal = 30, "925_silver"
    elif "18k gold" in text or "18 karat" in text:
        metal_score, detected_metal = 25, "18k_gold"
    elif "14k gold" in text:
        metal_score, detected_metal = 22, "14k_gold"
    elif "stainless steel" in text:
        metal_score, detected_metal = 20, "stainless_steel"
    elif "titanium" in text:
        metal_score, detected_metal = 20, "titanium"
    elif "surgical steel" in text:
        metal_score, detected_metal = 18, "surgical_steel"
    elif "gold filled" in text:
        metal_score, detected_metal = 18, "gold_filled"
    elif "gold plated" in text:
        metal_score, detected_metal = 12, "gold_plated"
    elif "silver plated" in text:
        metal_score, detected_metal = 10, "silver_plated"
    else:
        return _reject("Metal not specified — cannot verify material quality", metal="unknown")

    # ── STONE QUALITY (20 pts) ─────────────────────────────────
    stone_score = 10  # neutral — no stone is fine
    detected_stone = None

    if "moissanite" in text:
        stone_score, detected_stone = 20, "moissanite"
    elif "diamond" in text:
        stone_score, detected_stone = 20, "diamond"
    elif "natural" in text and any(g in text for g in [
            "ruby", "sapphire", "emerald", "topaz", "opal",
            "garnet", "amethyst", "gemstone", "stone"]):
        stone_score, detected_stone = 18, "natural_gemstone"
    elif "aaa zircon" in text or "real zircon" in text:
        stone_score, detected_stone = 15, "aaa_zircon"
    elif "cubic zirconia" in text or " cz " in text or text.endswith(" cz"):
        stone_score, detected_stone = 12, "cubic_zirconia"
    elif "crystal" in text:
        stone_score, detected_stone = 8, "crystal"
    elif "rhinestone" in text:
        stone_score, detected_stone = 5, "rhinestone"
    elif "fake" in text or "synthetic stone" in text:
        stone_score, detected_stone = 0, "fake"

    # ── PLATING QUALITY (20 pts) ───────────────────────────────
    plating_score = 5  # no plating info = neutral
    if "pvd" in text:
        plating_score = 20
    elif "18k gold plated" in text:
        plating_score = 16
    elif "14k gold plated" in text:
        plating_score = 14
    elif "gold plated" in text and any(kw in text for kw in
            ["thick", "micron", "heavy", "3 layer", "5 layer", "ion"]):
        plating_score = 12
    elif "gold plated" in text:
        plating_score = 8
    elif "silver plated" in text:
        plating_score = 6

    # ── SUPPLIER RATING (15 pts) ───────────────────────────────
    if supplier_rating == 0:
        rating_score = 8   # unknown → neutral
    elif supplier_rating >= 4.8:
        rating_score = 15
    elif supplier_rating >= 4.5:
        rating_score = 12
    elif supplier_rating >= 4.2:
        rating_score = 8
    else:
        rating_score = 5   # 4.0-4.1

    # ── IMAGE COUNT (10 pts) ───────────────────────────────────
    if image_count >= 5:
        image_score = 10
    elif image_count == 4:
        image_score = 8
    else:
        image_score = 6   # exactly 3

    # ── DESCRIPTION CLARITY (5 pts) ───────────────────────────
    spec_kws = ["925", "18k", "14k", "stainless", "titanium",
                "plated", "gold", "silver", "sterling", "surgical"]
    spec_count = sum(1 for kw in spec_kws if kw in text)
    if spec_count >= 3:
        desc_score = 5
    elif spec_count >= 1:
        desc_score = 3
    elif description:
        desc_score = 1
    else:
        desc_score = 0

    total = metal_score + stone_score + plating_score + rating_score + image_score + desc_score

    # ── Decisions ──────────────────────────────────────────────
    auto_import  = total >= 70
    needs_review = 50 <= total < 70
    rejected     = total < 50

    # ── Quality tier ───────────────────────────────────────────
    if total >= 85 and detected_stone in ("moissanite", "natural_gemstone", "diamond"):
        quality_tier = "ultra_luxury"
    elif total >= 70 and detected_metal in ("925_silver", "18k_gold", "14k_gold"):
        quality_tier = "luxury"
    elif total >= 60 and detected_metal in (
            "gold_plated", "stainless_steel", "surgical_steel", "titanium", "gold_filled", "pvd_plated"):
        quality_tier = "premium"
    else:
        quality_tier = "fashion"

    return {
        "score": total,
        "auto_import": auto_import,
        "needs_review": needs_review,
        "rejected": rejected,
        "rejection_reason": None if not rejected else f"Score {total}/100 below minimum 50",
        "quality_tier": quality_tier,
        "detected_metal": detected_metal,
        "detected_stone": detected_stone,
        "dimensions": {
            "metal_purity": metal_score,
            "stone_quality": stone_score,
            "plating_quality": plating_score,
            "supplier_rating": rating_score,
            "image_count": image_score,
            "description_clarity": desc_score,
        }
    }
