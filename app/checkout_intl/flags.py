"""Feature flag + tunables for the international checkout. Default OFF."""
import os

_TRUE = {"1", "true", "yes", "on"}


def intl_checkout_enabled() -> bool:
    """Env INTL_CHECKOUT wins; else StoreConfig 'intl_checkout_enabled'. Default False."""
    env = os.getenv("INTL_CHECKOUT")
    if env is not None:
        return env.strip().lower() in _TRUE
    try:
        from app.agents.store_config import get_config
        return str(get_config("intl_checkout_enabled", default="false")).strip().lower() in _TRUE
    except Exception:
        return False


def quote_ttl_minutes() -> int:
    try:
        return max(1, int(os.getenv("INTL_QUOTE_TTL_MIN", "15")))
    except ValueError:
        return 15


def tier_exposure() -> str:
    """
    Which delivery tiers customers may choose (both tiers are always quoted and
    persisted; this only controls what is OFFERED).

    'frozen' (default): ONE option -- EXPRESS when the supplier has one, else
    STANDARD. This mirrors today's "everything ships fast, cost absorbed in the
    price" economics, so exposing a cheaper/dearer choice cannot silently move
    margin before pricing can charge for it.
    'both': the cheapest STANDARD and the cheapest EXPRESS.
    'all' (default, owner decision 2026-09-24): every method the supplier offers for the
    country, each chosen individually. Prices are not charged yet (pricing stage).
    """
    v = os.getenv("INTL_TIER_EXPOSURE", "all").strip().lower()
    return v if v in ("frozen", "both", "all") else "all"


def quote_source() -> str:
    """
    'catalog' (default): delivery options come instantly from the Silverbene probe catalog
    (app/checkout_intl/catalog.py); countries not catalogued fall back to the live lookup.
    'live': always ask Silverbene at checkout (6-110 s per call).
    """
    v = os.getenv("INTL_QUOTE_SOURCE", "catalog").strip().lower()
    return v if v in ("catalog", "live") else "catalog"
