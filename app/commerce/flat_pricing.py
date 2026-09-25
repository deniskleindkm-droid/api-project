"""
Flat item price + separate Express delivery price (owner decision, 2026-09-24).

item price = wholesale + PROFIT + SUPPLIER_TAX + STANDARD_SHIPPING + payment fee, where the payment fee is a
percentage of the price (PayPal international basis), so the target profit holds at every price point:

    P = (W + PROFIT + SUPPLIER_TAX + STANDARD_SHIPPING + PAY_FIXED) / (1 - PAY_PCT)       rounded UP to a whole dollar

Standard delivery is included in the item price ($0 at checkout). Express is shown at the FULL DHL price.
Enabled with PRICING_MODEL=flat_v2 (default off); use it together with INTL_CHECKOUT, which is what charges Express.
"""
import math
import os

PROFIT = 45.0
SUPPLIER_TAX = 8.5          # constant per order (owner)
STANDARD_SHIPPING = 8.0     # constant, absorbed in the item price (owner)
PAY_PCT = 0.0499            # PayPal international; Stripe is cheaper, so Stripe orders earn slightly more
PAY_FIXED = 0.49

# SilverBene US DHL quote (duty at 22.5% included): observed 55.49-57.83 for single items, ~ 51.83 + 22.5% of wholesale.
US_DHL_BASE, US_DHL_DUTY = 51.83, 0.225


def enabled() -> bool:
    return os.getenv("PRICING_MODEL", "").strip().lower() == "flat_v2"


def item_price(wholesale: float) -> float:
    p = (wholesale + PROFIT + SUPPLIER_TAX + STANDARD_SHIPPING + PAY_FIXED) / (1 - PAY_PCT)
    return float(math.ceil(p - 1e-9))


def us_express_price(cart_wholesale: float) -> float:
    return float(math.ceil(US_DHL_BASE + US_DHL_DUTY * cart_wholesale - 1e-9))


def express_price(country: str, cart_wholesale: float, observed_max: float) -> float:
    """Full DHL price the customer pays for Express. US follows the wholesale-driven formula; other countries the
    highest observed DHL quote (their duty/VAT effect is small or flat)."""
    if country.upper() == "US":
        return us_express_price(cart_wholesale)
    return float(math.ceil(observed_max - 1e-9))


def profit_standard(price: float, wholesale: float) -> float:
    return price - wholesale - SUPPLIER_TAX - STANDARD_SHIPPING - (PAY_PCT * price + PAY_FIXED)
