"""
Shipping agent — fetches real shipping cost from supplier API.
Always returns something; never blocks an import.
"""

from app.agents.store_config import get_config


def get_best_shipping(supplier: str, vid: str, destination: str = "US") -> dict:
    """
    Fetch the fastest available shipping method for a supplier variant.
    Falls back to StoreConfig defaults if API unavailable.
    """
    fallback = {
        "method": "Standard Shipping",
        "cost": float(get_config("shipping_fallback_cost", default=4.50)),
        "days_min": 7,
        "days_max": int(float(get_config("shipping_max_days", default=12))),
        "carrier": "Standard",
        "tracking": True,
        "is_fallback": True,
    }

    if not vid:
        return fallback

    sup = supplier.lower()

    if any(s in sup for s in ("cjdropshipping", "cj")):
        try:
            from app.agents.cj_dropshipping import get_shipping_methods
            methods = get_shipping_methods(vid, destination)
            if not methods:
                return fallback

            # Sort ascending by delivery days
            def _days(m):
                aging = m.get("logisticAging") or m.get("aginStr") or "99"
                try:
                    return int(str(aging).split("-")[0].strip())
                except Exception:
                    return 99

            sorted_methods = sorted(methods, key=_days)
            fastest = sorted_methods[0]
            days = _days(fastest)

            return {
                "method": fastest.get("logisticName", "CJ Shipping"),
                "cost": float(fastest.get("logisticPrice", 0) or 0),
                "days_min": days,
                "days_max": days + 3,
                "carrier": fastest.get("logisticName", "CJ"),
                "tracking": True,
                "is_fallback": False,
            }

        except Exception as e:
            print(f"[Shipping] CJ lookup failed for vid={vid}: {e} — using fallback")
            return fallback

    # Unknown supplier — return fallback
    return fallback
