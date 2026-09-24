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
    'both': the cheapest STANDARD and the cheapest EXPRESS. Enable only once the
    pricing stage charges for the chosen tier.
    """
    v = os.getenv("INTL_TIER_EXPOSURE", "frozen").strip().lower()
    return v if v in ("frozen", "both") else "frozen"
