"""
Supplier-backed market registry.

Every ISO country is REPRESENTABLE here, but none is checkout-enabled merely
because it exists. A market is enabled only when BOTH hold:
  1. it is in the enabled set (default below, override via StoreConfig
     'intl_enabled_countries' as a comma list -- no code change needed), and
  2. Silverbene can actually return a shipping route for the customer's real
     address (checked live in the Delivery step -- see routes/intl_checkout).

Silverbene's `country_id` is the ISO alpha-2 code in the only contract this
repo proves (place_order sends address["country_code"] straight through, and
US/CA/GB/AU orders have flowed that way). SUPPLIER_COUNTRY_ID_OVERRIDES
is the single place to record any country where authenticated docs / a live
probe show Silverbene uses a different id.

Fields that are unknown (supplier_supported / families) are filled by
scripts/probe_silverbene_markets.py, which writes artifacts/
silverbene_market_probe.json; that file, when present, is overlaid here.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.checkout_intl._iso_countries import ISO_COUNTRIES

# Launch plan (evidence: Silverbene runs dedicated fast dropshipping lanes to exactly
# these six -- US/USPS, GB/Hermes, DE/DHL Global Mail, FR/La Poste, AU/Australia Post,
# CA/Canada Post). "Candidate" means engineering/qualification priority, NOT
# production enablement.
LAUNCH_WAVE_1 = ("US", "GB", "DE", "FR", "AU", "CA")
LAUNCH_WAVE_2_CANDIDATE = ("CH", "JP", "SG", "NZ")

# Markets that are checkout-enabled by default when the flag is on. DE and FR are
# Wave-1 candidates that stay OFF until they are qualified (shipping probe, EU
# VAT/payment work) and enabled explicitly via INTL_ENABLED_COUNTRIES or
# StoreConfig 'intl_enabled_countries'. NG and GH were removed from the rollout:
# they remain inert ISO records (checkout_enabled=False, no qualification work).
DEFAULT_ENABLED = ("US", "GB", "AU", "CA")

# Legal/payment-provider market restrictions are NOT a constant here -- they live
# in the versioned compliance policy (app/checkout_intl/compliance.py) with
# source, jurisdiction, effective date, reason and review date.

# ISO -> Silverbene country_id where they differ. Empty until proven.
SUPPLIER_COUNTRY_ID_OVERRIDES: Dict[str, str] = {}

_DEFAULT_POSTAL = r"^[A-Za-z0-9][A-Za-z0-9 \-]{1,10}[A-Za-z0-9]$"


@dataclass(frozen=True)
class AddressRules:
    state_required: bool = False
    state_label: str = "State / Province / Region"
    postal_required: bool = True
    postal_label: str = "Postal code"
    postal_regex: str = _DEFAULT_POSTAL
    postal_example: str = ""


_R = AddressRules
_ADDRESS_RULES: Dict[str, AddressRules] = {
    "US": _R(True, "State", True, "ZIP code", r"^\d{5}(-\d{4})?$", "10001"),
    "CA": _R(True, "Province", True, "Postal code", r"^[A-Za-z]\d[A-Za-z][ \-]?\d[A-Za-z]\d$", "K1A 0B1"),
    "GB": _R(False, "County (optional)", True, "Postcode",
             r"^[A-Za-z]{1,2}\d[A-Za-z\d]? ?\d[A-Za-z]{2}$", "SW1A 1AA"),
    "AU": _R(True, "State / Territory", True, "Postcode", r"^\d{4}$", "2000"),
    "NZ": _R(False, "Region (optional)", True, "Postcode", r"^\d{4}$", "6011"),
    "DE": _R(False, "State (optional)", True, "Postleitzahl", r"^\d{5}$", "10115"),
    "FR": _R(False, "Region (optional)", True, "Code postal", r"^\d{5}$", "75001"),
    "ES": _R(False, "Province (optional)", True, "Código postal", r"^\d{5}$", "28001"),
    "IT": _R(False, "Province (optional)", True, "CAP", r"^\d{5}$", "00100"),
    "NL": _R(False, "Province (optional)", True, "Postcode", r"^\d{4} ?[A-Za-z]{2}$", "1012 AB"),
    "BE": _R(False, "Province (optional)", True, "Postcode", r"^\d{4}$", "1000"),
    "AT": _R(False, "State (optional)", True, "Postleitzahl", r"^\d{4}$", "1010"),
    "CH": _R(False, "Canton (optional)", True, "Postleitzahl", r"^\d{4}$", "8001"),
    "SE": _R(False, "County (optional)", True, "Postnummer", r"^\d{3} ?\d{2}$", "111 22"),
    "DK": _R(False, "Region (optional)", True, "Postnummer", r"^\d{4}$", "1050"),
    "NO": _R(False, "County (optional)", True, "Postnummer", r"^\d{4}$", "0150"),
    "PL": _R(False, "Voivodeship (optional)", True, "Kod pocztowy", r"^\d{2}-?\d{3}$", "00-001"),
    "PT": _R(False, "District (optional)", True, "Código postal", r"^\d{4}(-\d{3})?$", "1000-001"),
    "IE": _R(True, "County", True, "Eircode", r"^[A-Za-z\d]{3} ?[A-Za-z\d]{4}$", "D02 X285"),
    "JP": _R(True, "Prefecture", True, "Postal code", r"^\d{3}-?\d{4}$", "100-0001"),
    "KR": _R(False, "Province (optional)", True, "Postal code", r"^\d{5}$", "04524"),
    "SG": _R(False, "State (optional)", True, "Postal code", r"^\d{6}$", "018956"),
    "MX": _R(True, "State", True, "Código postal", r"^\d{5}$", "06000"),
    "BR": _R(True, "State", True, "CEP", r"^\d{5}-?\d{3}$", "01310-100"),
    "IN": _R(True, "State", True, "PIN code", r"^\d{6}$", "110001"),
    "ZA": _R(True, "Province", True, "Postal code", r"^\d{4}$", "0001"),
    # Countries whose postal systems legitimately have no/optional postcodes.
    "AE": _R(True, "Emirate", False, "Postal code (optional)"),
    "HK": _R(False, "District (optional)", False, "Postal code (optional)"),
    "QA": _R(False, "Region (optional)", False, "Postal code (optional)"),
    "KE": _R(False, "County (optional)", False, "Postal code (optional)"),
    "IL": _R(False, "District (optional)", True, "Postal code", r"^\d{5,7}$", "6100000"),
}


@dataclass
class SupplierMarket:
    iso_country_code: str
    display_name: str
    silverbene_country_id: str
    supplier_supported: Optional[bool]          # None = not yet probed
    shipping_families: List[str] = field(default_factory=list)   # e.g. ["dhl", "epacket"]; [] = unknown
    standard_shipping_capable: Optional[bool] = None
    express_shipping_capable: Optional[bool] = None
    address_rules: AddressRules = field(default_factory=AddressRules)
    checkout_enabled: bool = False

    def public_dict(self) -> dict:
        r = self.address_rules
        return {
            "code": self.iso_country_code,
            "name": self.display_name,
            "state_required": r.state_required,
            "state_label": r.state_label,
            "postal_required": r.postal_required,
            "postal_label": r.postal_label,
            "postal_example": r.postal_example,
        }


_NAMES = {c: n for c, n in ISO_COUNTRIES}
_probe_cache: Optional[dict] = None


def _probe_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "silverbene_market_probe.json")


def _load_probe() -> dict:
    global _probe_cache
    if _probe_cache is None:
        try:
            with open(_probe_path(), encoding="utf-8") as f:
                _probe_cache = json.load(f).get("markets", {})
        except (OSError, ValueError):
            _probe_cache = {}
    return _probe_cache


def reset_probe_cache() -> None:
    global _probe_cache
    _probe_cache = None


def enabled_country_codes() -> set:
    """Env INTL_ENABLED_COUNTRIES > StoreConfig 'intl_enabled_countries' > DEFAULT_ENABLED,
    minus anything the compliance policy currently blocks."""
    from app.checkout_intl import compliance
    raw = os.getenv("INTL_ENABLED_COUNTRIES")
    if not raw:
        try:
            from app.agents.store_config import get_config
            raw = get_config("intl_enabled_countries", default=None)
        except Exception:
            raw = None
    codes = (
        {c.strip().upper() for c in str(raw).split(",") if c.strip()}
        if raw else set(DEFAULT_ENABLED)
    )
    return {c for c in codes if c in _NAMES and not compliance.is_blocked(c)}


def get_market(code: str) -> Optional[SupplierMarket]:
    code = (code or "").strip().upper()
    if code not in _NAMES:            # "other", "", "XX" and every non-ISO value stop here
        return None
    probe = _load_probe().get(code, {})
    return SupplierMarket(
        iso_country_code=code,
        display_name=_NAMES[code],
        silverbene_country_id=SUPPLIER_COUNTRY_ID_OVERRIDES.get(code, code),
        supplier_supported=probe.get("supplier_supported"),
        shipping_families=list(probe.get("families", [])),
        standard_shipping_capable=probe.get("standard"),
        express_shipping_capable=probe.get("express"),
        address_rules=_ADDRESS_RULES.get(code, AddressRules()),
        checkout_enabled=code in enabled_country_codes(),
    )


def all_markets() -> List[SupplierMarket]:
    return [get_market(c) for c, _ in ISO_COUNTRIES]


def checkout_markets() -> List[SupplierMarket]:
    """Markets the customer selector may show: enabled and not probed-unsupported."""
    return [m for m in all_markets() if m.checkout_enabled and m.supplier_supported is not False]


def is_checkout_country(code: str) -> bool:
    m = get_market(code)
    return bool(m and m.checkout_enabled and m.supplier_supported is not False)


def validate_postal(code: str, postal: str) -> Optional[str]:
    """Error message, or None if acceptable for that country."""
    m = get_market(code)
    rules = m.address_rules if m else AddressRules()
    postal = (postal or "").strip()
    if not postal:
        return f"Please enter your {rules.postal_label}" if rules.postal_required else None
    if not re.match(rules.postal_regex, postal):
        hint = f" (e.g. {rules.postal_example})" if rules.postal_example else ""
        return f"Please enter a valid {rules.postal_label}{hint}"
    return None
