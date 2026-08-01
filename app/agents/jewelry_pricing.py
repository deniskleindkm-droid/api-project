"""
Mikisi pricing engine — single source of truth for import and bulk repricing.
Tiered flat-profit model: fixed dollar profit per wholesale cost band.
Real per-product shipping cost (see get_real_shipping_cost) and packaging
are absorbed into the retail price.
"""
import math

USPS_SHIPPING = 9.51  # fallback only — used when a real per-option quote can't be fetched
PACKAGING     = 3.00
STRIPE_RATE   = 0.029
STRIPE_FIXED  = 0.30

# Reference US address used to price shipping at import time — no real
# customer address exists yet, so this stands in purely to get a
# representative Silverbene quote for the product/option itself.
_REFERENCE_POSTCODE = "10001"
_REFERENCE_CITY     = "New York"


def get_real_shipping_cost(option_id: str) -> float:
    """
    Real cheapest Silverbene shipping cost for this option, or USPS_SHIPPING
    if the lookup fails/returns nothing.

    Why this exists: the flat $9.51 USPS assumption baked into every tier
    was wrong whenever Silverbene doesn't offer USPS for a product (not a
    clean price cutoff — confirmed live 2026-08-01 that a $40 item can lose
    USPS eligibility while $50-58 items keep it, so it can't be predicted
    from cost alone). When that happens, the real cheapest option is
    DHL/FedEx at $58-88, not $9.51 — order #22 shipped at $53.12 real cost
    against a $9.51 budget and kept only ~$4 of a stated $45 profit tier.
    Querying Silverbene's real quote per product at import time closes that
    gap for every tier, not just premium.
    """
    if not option_id:
        return USPS_SHIPPING
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        methods = SilverbeneAdapter().get_shipping_methods(
            "US", option_id=str(option_id), qty=1,
            postcode=_REFERENCE_POSTCODE, city=_REFERENCE_CITY,
        )
        if methods:
            return min(m.get("price", USPS_SHIPPING) for m in methods)
    except Exception as e:
        print(f"[Pricing] Shipping cost lookup failed for option_id={option_id}: {e}")
    return USPS_SHIPPING

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
                           discount_percent: float = 0.0,
                           option_id: str = None,
                           shipping_cost: float = None) -> dict:
    """
    Calculate final Mikisi retail price from Silverbene wholesale cost.

    Tiers (profit added on top of cost + shipping + packaging):
      entry     cost < $12   → +$30
      core      $12–$30      → +$45
      statement $30–$60      → +$60
      premium   > $60        → +cost × 2

    Real shipping cost (see get_real_shipping_cost) + packaging ($3.00) +
    Stripe (2.9% + $0.30) all absorbed.

    Two ways to supply the real cost, checked in this order:
      shipping_cost — an already-known real quote (e.g. Product.shipping_cost,
        captured once at import time). Use this for recurring resyncs
        (stock sync, price drift checks) so they reuse the real number
        already on file instead of re-querying Silverbene's shipping API
        on every cycle for every variant — that doesn't scale (hundreds of
        products, every 6h).
      option_id — fetches a fresh real quote via get_real_shipping_cost.
        Use this only at the one-time pricing decision (new import, or a
        genuine cost-change resync where no prior shipping_cost exists
        yet) since it's a live API call.
    Falls back to the flat $9.51 USPS assumption only if neither is given
    — without one of these, every tier is exposed to the same profit-eating
    gap that hit order #22 (see get_real_shipping_cost's docstring).
    `material` is kept for backward compatibility but no longer affects pricing.
    """
    if shipping_cost is None:
        shipping_cost = get_real_shipping_cost(option_id) if option_id else USPS_SHIPPING
    profit, tier = profit_tier(silverbene_cost)
    base   = silverbene_cost + shipping_cost + PACKAGING + profit
    retail = elegant_round((base + STRIPE_FIXED) / (1 - STRIPE_RATE))

    if discount_percent > 0:
        original_price = elegant_round(retail / (1 - discount_percent / 100))
    else:
        original_price = retail

    return {
        "final_price":      retail,
        "original_price":   original_price,
        "discount_percent": discount_percent,
        "shipping_cost":    shipping_cost,
        "markup_used":      profit,
        "material":         material or "silver",
        "tier":             tier,
    }


# Alias for any callers using the older function name
calculate_jewelry_price = calculate_mikisi_price
