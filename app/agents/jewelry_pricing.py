"""
Mikisi pricing engine — single source of truth for import and bulk repricing.
Tiered flat-profit model: fixed dollar profit per wholesale cost band.
USPS shipping and packaging are absorbed into the retail price.
"""
import math

USPS_SHIPPING = 9.51
PACKAGING     = 3.00
STRIPE_RATE   = 0.029
STRIPE_FIXED  = 0.30

# Checked in priority order — moissanite first so it wins over silver keywords
MATERIAL_KEYWORDS = {
    "moissanite":     ["moissanite", "d color", "vvs"],
    "pearl":          ["pearl", "freshwater", "cultured"],
    "semi_precious":  ["turquoise", "sapphire", "ruby", "emerald",
                       "amethyst", "topaz", "opal", "garnet"],
    "cubic_zirconia": ["cz", "cubic zirconia", "zircon", "crystal"],
    "rose_gold":      ["rose gold"],
    "white_gold":     ["white gold"],
    "gold":           ["gold plat", "18k gold", "14k gold", "yellow gold"],
    "rhodium":        ["rhodium"],
    "silver":         ["silver", "sterling", "925"],
}


def detect_material(name: str, options: list = None) -> str:
    """Detect material key from product name and Silverbene option attributes."""
    option_texts = []
    if options:
        for opt in options:
            if isinstance(opt, dict):
                for attr in opt.get("attribute", []):
                    v = attr.get("value", "")
                    if v:
                        option_texts.append(v.lower())
            elif isinstance(opt, str):
                option_texts.append(opt.lower())

    option_str = " ".join(option_texts)
    name_lower = (name or "").lower()

    for mat, keywords in MATERIAL_KEYWORDS.items():
        for kw in keywords:
            if option_str and kw in option_str:
                return mat

    for mat, keywords in MATERIAL_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return mat

    return "silver"


def profit_tier(wholesale: float) -> tuple:
    """Return (profit_amount, tier_label) for a given wholesale cost."""
    if wholesale < 12:
        return 30.0,          "entry"
    elif wholesale <= 30:
        return 45.0,          "core"
    elif wholesale <= 60:
        return 60.0,          "statement"
    else:
        return wholesale * 2, "premium"


def elegant_round(price: float) -> float:
    """Round up to nearest price ending in .00 or .90."""
    whole = math.floor(price)
    candidates = [float(whole), whole + 0.90, float(whole + 1)]
    valid = [c for c in candidates if c >= price - 0.001]
    return min(valid) if valid else float(whole + 1)


def calculate_mikisi_price(silverbene_cost: float, material: str = None,
                           discount_percent: float = 0.0) -> dict:
    """
    Calculate final Mikisi retail price from Silverbene wholesale cost.

    Tiers (profit added on top of cost + shipping + packaging):
      entry     cost < $12   → +$30
      core      $12–$30      → +$45
      statement $30–$60      → +$60
      premium   > $60        → +cost × 2

    USPS ($9.51) + packaging ($3.00) + Stripe (2.9% + $0.30) all absorbed.
    `material` is kept for backward compatibility but no longer affects pricing.
    """
    profit, tier = profit_tier(silverbene_cost)
    base   = silverbene_cost + USPS_SHIPPING + PACKAGING + profit
    retail = elegant_round((base + STRIPE_FIXED) / (1 - STRIPE_RATE))

    if discount_percent > 0:
        original_price = elegant_round(retail / (1 - discount_percent / 100))
    else:
        original_price = retail

    return {
        "final_price":      retail,
        "original_price":   original_price,
        "discount_percent": discount_percent,
        "shipping_cost":    USPS_SHIPPING,
        "markup_used":      profit,
        "material":         material or "silver",
        "tier":             tier,
    }


# Alias for any callers using the older function name
calculate_jewelry_price = calculate_mikisi_price
