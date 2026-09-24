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


def shipping_policy() -> str:
    """
    'dhl_only' (default) preserves today's economics -- Dennis's standing rule
    is every order ships DHL, with the cost absorbed in the price. 'all'
    presents every Silverbene method to the customer; enable it only once
    pricing (a later stage) can charge for the chosen service.
    """
    return os.getenv("INTL_SHIPPING_POLICY", "dhl_only").strip().lower()
