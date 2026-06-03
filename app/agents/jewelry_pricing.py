"""
Mikisi pricing engine for Silverbene products.
Formula: (cost × markup + SHIPPING_USA + stripe_absorb) → rounded elegantly
"""
import math

SHIPPING_USA = 18.00
STRIPE_RATE  = 0.029
STRIPE_FIXED = 0.30

MATERIAL_MARKUP = {
    "silver":         4.5,
    "rhodium":        4.5,
    "gold":           4.5,
    "rose_gold":      4.5,
    "white_gold":     4.5,
    "cubic_zirconia": 4.5,
    "pearl":          4.8,
    "semi_precious":  5.0,
    "moissanite":     5.5,
}

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
    """
    Detect material key from product name and Silverbene option attributes.
    Options checked first, then name. Returns a key from MATERIAL_MARKUP.
    """
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


def round_to_elegant(price: float) -> float:
    """
    under $25  → nearest dollar - $0.01  (e.g. $19.99)
    $25–$99    → round up to nearest $5, then -1  (e.g. $49, $79)
    $100+      → round up to nearest $10, then -1  (e.g. $109, $199)
    """
    if price < 25:
        return float(round(price)) - 0.01
    elif price < 100:
        return float(math.ceil(price / 5) * 5 - 1)
    else:
        return float(math.ceil(price / 10) * 10 - 1)


def calculate_mikisi_price(silverbene_cost: float, material: str,
                           discount_percent: float = 0.0) -> dict:
    """
    Calculate final Mikisi price from Silverbene wholesale cost and material key.
    Absorbs Stripe fees so margin stays clean.

    discount_percent: optional sale discount — when > 0, original_price is set
    higher so the displayed price becomes the discounted one.
    Returns a full pricing breakdown dict.
    """
    markup = MATERIAL_MARKUP.get(material, 4.5)
    base = silverbene_cost * markup
    with_shipping = base + SHIPPING_USA
    with_stripe = (with_shipping + STRIPE_FIXED) / (1 - STRIPE_RATE)
    final_price = round_to_elegant(with_stripe)

    if discount_percent > 0:
        original_price = round_to_elegant(final_price / (1 - discount_percent / 100))
    else:
        original_price = final_price

    return {
        "final_price":      final_price,
        "original_price":   original_price,
        "discount_percent": discount_percent,
        "shipping_cost":    SHIPPING_USA,
        "markup_used":      markup,
        "material":         material,
    }
