"""
Mikisi pricing engine — single source of truth for import and bulk repricing.

Flat-overhead luxury-ladder model (replaced the real-per-product-shipping-
quote model 2026-08-09, per Dennis): every order ships free DHL Express to
the customer, but that $50 plus $17 taxes/fees is a fixed $67 overhead
absorbed into the retail price on every product, no live Silverbene
shipping lookup needed. Retail price is picked from a fixed luxury price
ladder (never an arbitrary number), so the storefront always shows round,
intentional-looking prices.
"""

# Constants ── everything a customer sees as "Free DHL Express Delivery"
DHL_SHIPPING   = 50.0
TAXES_AND_FEES = 17.0
FIXED_OVERHEAD = DHL_SHIPPING + TAXES_AND_FEES  # $67, absorbed into every price

# Round to the nearest of these, never below — this is what makes the
# storefront feel intentional instead of showing whatever number a formula
# happened to spit out. $98/$128 are the only rungs below Dennis's stated
# $128 floor; they exist for a deliberate low-cost/entry item, not the
# typical product. Rungs above $698 (798+) extend Dennis's own ladder for
# real catalog outliers his worked examples didn't cover — found live
# 2026-08-09: a handful of real products (moissanite/zirconia pieces) cost
# $150–961 wholesale, and hard-capping at $698 would sell several of them
# at a real loss (e.g. a $958 cost item capped at $698 loses $327/unit).
# Dennis confirmed extending the ladder upward rather than capping.
LUXURY_LADDER = [98, 128, 148, 168, 198, 228, 248, 298, 348, 398, 448, 498, 598, 698,
                  798, 898, 998, 1098, 1198, 1398, 1598]

# (product_cost, selling_price) anchor points — Dennis's own worked
# examples up to cost=120. Real costs get linearly interpolated between
# these (and extrapolated beyond the ends using the nearest segment's
# slope), then rounded UP to the nearest LUXURY_LADDER rung. This is a
# lookup, not a closed-form formula, because the worked examples don't
# follow one constant markup or margin: profit above (cost + $67) grows by
# ~$4 per $1 of cost in the $60–80 segment but only ~$1.50 per $1 of cost
# in the $100–120 segment — these prices were chosen by feel for "a good
# round luxury number with healthy margin," not computed. Interpolating
# between them is the only way to extend that judgment smoothly to costs
# in between without silently drifting from the anchors Dennis actually
# gave.
#
# Anchors above 120 (150 through 1000) are this codebase's own extension,
# not from Dennis's worked examples — none of his examples went past
# cost=120, but real products do (see LUXURY_LADDER's comment). Built by
# continuing the same "round ladder number, healthy and still-growing
# absolute profit" judgment the given examples already show, landing each
# one exactly on a new ladder rung the same way the original anchors do.
_PRICE_ANCHORS = [
    (20, 148), (30, 198), (40, 228), (50, 248), (60, 298),
    (70, 348), (80, 398), (100, 448), (120, 498),
    (150, 598), (180, 698), (220, 798), (280, 898), (350, 998),
    (450, 1098), (600, 1198), (800, 1398), (1000, 1598),
]


def round_to_ladder(price: float) -> float:
    """Rounds UP to the nearest LUXURY_LADDER rung — never down, so rounding never quietly gives away margin."""
    for rung in LUXURY_LADDER:
        if rung >= price - 0.001:
            return float(rung)
    return float(LUXURY_LADDER[-1])  # cost so high even the top rung would undercut it — capped; see price_tier_label


def _interpolated_price(cost: float) -> float:
    """Straight-line interpolation/extrapolation across _PRICE_ANCHORS. Internal — calculate_mikisi_price rounds the result to the real ladder."""
    anchors = _PRICE_ANCHORS
    if cost <= anchors[0][0]:
        (x0, y0), (x1, y1) = anchors[0], anchors[1]
    elif cost >= anchors[-1][0]:
        (x0, y0), (x1, y1) = anchors[-2], anchors[-1]
    else:
        (x0, y0), (x1, y1) = next(
            (anchors[i], anchors[i + 1]) for i in range(len(anchors) - 1)
            if anchors[i][0] <= cost <= anchors[i + 1][0]
        )
    slope = (y1 - y0) / (x1 - x0)
    return y0 + slope * (cost - x0)


def price_tier_label(retail: float) -> str:
    """Everyday / Signature / Premium — matches Dennis's 3-tier naming, by final retail price rather than cost."""
    if retail <= 198:
        return "everyday"
    elif retail <= 298:
        return "signature"
    else:
        return "premium"


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


def calculate_mikisi_price(silverbene_cost: float, material: str = None,
                           discount_percent: float = 0.0,
                           option_id: str = None,
                           shipping_cost: float = None) -> dict:
    """
    Calculate final Mikisi retail price from Silverbene wholesale cost.

    Selling Price = Product Cost + $67 fixed overhead ($50 DHL Express +
    $17 taxes/fees) + Desired Profit — where Desired Profit is read off
    Dennis's own price ladder via interpolation (see _PRICE_ANCHORS)
    rather than a fixed formula, then rounded UP to the nearest
    LUXURY_LADDER rung.

    `option_id` and `shipping_cost` are accepted only for backward
    compatibility with every existing call site (import, ProductVariant
    creation, stock-sync resync, legacy fallback, pending backfill) — the
    old model needed a real per-product Silverbene shipping quote here;
    the new one doesn't, since shipping is always the flat $50 DHL
    Express absorbed into the price (customers see "Free DHL Express
    Delivery"). No live shipping API call happens in this function
    anymore. `material` is kept for backward compatibility but doesn't
    affect pricing.
    """
    retail = round_to_ladder(_interpolated_price(silverbene_cost))
    profit = retail - silverbene_cost - FIXED_OVERHEAD

    if discount_percent > 0:
        original_price = round_to_ladder(retail / (1 - discount_percent / 100))
    else:
        original_price = retail

    return {
        "final_price":      retail,
        "original_price":   original_price,
        "discount_percent": discount_percent,
        "shipping_cost":    DHL_SHIPPING,
        "markup_used":      profit,
        "material":         material or "silver",
        "tier":             price_tier_label(retail),
    }


# Alias for any callers using the older function name
calculate_jewelry_price = calculate_mikisi_price
