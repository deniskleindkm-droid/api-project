"""
Jewelry pricing engine.
All multipliers read from StoreConfig — nothing hardcoded.
Formula: raw = cost × base × quality_adj × supplier_adj × score_bonus
final = raw + shipping + packaging, floored, ceilinged, rounded to .99
"""

from app.agents.store_config import get_config


def _detect_category(name: str) -> tuple:
    """Returns (config_key, category_label)."""
    n = name.lower()
    if any(w in n for w in ["ring", "band", "solitaire", "knuckle"]):
        return "pricing_multiplier_rings", "rings"
    if any(w in n for w in ["necklace", "pendant", "chain", "choker", "lariat"]):
        return "pricing_multiplier_necklaces", "necklaces"
    if any(w in n for w in ["bracelet", "bangle", "cuff"]):
        return "pricing_multiplier_bracelets", "bracelets"
    if any(w in n for w in ["earring", "stud", "hoop", "drop", "ear cuff", "huggie", "threader"]):
        return "pricing_multiplier_earrings", "earrings"
    if any(w in n for w in ["anklet", "ankle"]):
        return "pricing_multiplier_anklets", "anklets"
    if any(w in n for w in ["piercing", "nose", "cartilage", "belly button", "navel", "septum", "body jewelry"]):
        return "pricing_multiplier_piercings", "piercings"
    return "pricing_multiplier_necklaces", "unknown"


_METAL_ADJ_MAP = {
    "moissanite":      "pricing_adj_moissanite",
    "diamond":         "pricing_adj_moissanite",
    "natural_gemstone":"pricing_adj_natural_gemstone",
    "aaa_zircon":      "pricing_adj_925_silver",
    "925_silver":      "pricing_adj_925_silver",
    "18k_gold":        "pricing_adj_18k_gold",
    "14k_gold":        "pricing_adj_18k_gold",
    "gold_filled":     "pricing_adj_18k_gold",
    "pvd_plated":      "pricing_adj_pvd_plating",
    "gold_plated":     "pricing_adj_gold_plated",
    "silver_plated":   "pricing_adj_gold_plated",
    "stainless_steel": "pricing_adj_gold_plated",
    "surgical_steel":  "pricing_adj_gold_plated",
    "titanium":        "pricing_adj_gold_plated",
    "unknown":         "pricing_adj_unknown_metal",
}

_STONE_BOOST = {
    "moissanite":      "pricing_adj_moissanite",
    "diamond":         "pricing_adj_moissanite",
    "natural_gemstone":"pricing_adj_natural_gemstone",
}

_SUPPLIER_MAP = {
    "silverbene":     "pricing_supplier_silverbene",
    "nihaojewelry":   "pricing_supplier_nihaojewelry",
    "nihao":          "pricing_supplier_nihaojewelry",
    "cjdropshipping": "pricing_supplier_cj",
    "cj":             "pricing_supplier_cj",
}


def calculate_jewelry_price(product: dict, score: dict, shipping_cost: float = 0.0) -> dict:
    """
    Calculate final store price from cost price + score + shipping.
    Returns full pricing breakdown dict.
    """
    name = product.get("name", "")
    cost_price = float(product.get("cost_price", 0))
    supplier = product.get("supplier_name", "cj").lower()
    quality_tier = score.get("quality_tier", "fashion")
    detected_metal = score.get("detected_metal") or "unknown"
    detected_stone = score.get("detected_stone")
    score_val = int(score.get("score", 0))

    # Base multiplier
    mkey, category_label = _detect_category(name)
    base = float(get_config(mkey, default=7.0))

    # Quality adjustment from metal
    adj_key = _METAL_ADJ_MAP.get(detected_metal, "pricing_adj_unknown_metal")
    quality_adj = float(get_config(adj_key, default=1.0))

    # Stone boost (take max of metal adj and stone adj)
    if detected_stone and detected_stone in _STONE_BOOST:
        stone_adj = float(get_config(_STONE_BOOST[detected_stone], default=1.0))
        quality_adj = max(quality_adj, stone_adj)

    # Supplier adjustment
    supplier_key = next(
        (v for k, v in _SUPPLIER_MAP.items() if k in supplier),
        "pricing_supplier_cj"
    )
    supplier_adj = float(get_config(supplier_key, default=1.0))

    # Score bonus
    if score_val >= 90:
        score_bonus = 1.15
    elif score_val >= 70:
        score_bonus = 1.05
    else:
        score_bonus = 1.0

    # Packaging from tier
    if quality_tier in ("luxury", "ultra_luxury"):
        packaging = float(get_config("packaging_cost_premium", default=3.0))
    else:
        packaging = float(get_config("packaging_cost_standard", default=1.5))

    # Raw calculation
    raw_price = cost_price * base * quality_adj * supplier_adj * score_bonus
    pre_final = raw_price + shipping_cost + packaging

    # Floor
    floor = float(get_config("pricing_floor", default=10.99))
    pre_final = max(floor, pre_final)

    # Ceiling by tier
    ceiling_key = f"pricing_ceiling_{quality_tier}"
    ceiling = float(get_config(ceiling_key, default=80.0))
    pre_final = min(pre_final, ceiling)

    # Round to .99
    final_price = round(pre_final - 0.01, 0) + 0.99
    original_price = round(final_price * 1.35 - 0.01, 0) + 0.99
    discount_percent = round((1 - final_price / original_price) * 100)

    return {
        "final_price": final_price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "cost_price": cost_price,
        "shipping_cost": shipping_cost,
        "packaging_cost": packaging,
        "raw_price": round(raw_price, 2),
        "category_detected": category_label,
        "base_multiplier": base,
        "quality_adj": quality_adj,
        "supplier_adj": supplier_adj,
        "score_bonus": score_bonus,
        "quality_tier": quality_tier,
    }
