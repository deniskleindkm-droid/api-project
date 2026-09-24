"""
Structured international address + the three views of it:
  - what Mikisi collects (everything below),
  - the legacy comma string older code (Order.shipping_address, recovery,
    emails) still reads,
  - the minimal subset sent to Silverbene (data minimization).

Silverbene receives ONLY the fields its proven create_order contract
carries: firstname, lastname, telephone, street, city, region, postcode,
country_id, plus the store's own admin email (never the customer's).
Company, tax/customs ID, delivery note and the customer's email are
collected for Mikisi's use and are NOT transmitted until the authenticated
Silverbene contract confirms a field for them.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from app.checkout_intl import countries

ADMIN_SUPPLIER_EMAIL = "hello@mikisi.co"


class StructuredAddress(BaseModel):
    first_name: str
    last_name: str
    phone: str
    email: str
    line1: str
    line2: str = ""
    city: str
    admin_area: str = ""          # state / province / prefecture -- country-aware requirement
    postal_code: str = ""
    country_code: str
    company: str = ""
    customs_tax_id: str = ""      # VAT / EORI / tax ID -- only collected where a market's policy needs it
    delivery_note: str = ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def validate_phone(phone: str) -> Optional[str]:
    """Same rule as the legacy gate (payments._validate_phone) so behavior can't diverge."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 7:
        return "Please enter a complete phone number"
    if len(set(digits)) == 1:
        return "Please enter a valid phone number"
    return None


def validate(addr: StructuredAddress) -> Optional[str]:
    """First problem found as a customer-facing message, else None."""
    if not _clean(addr.first_name) or not _clean(addr.last_name):
        return "Please enter your first and last name"
    if "@" not in (addr.email or ""):
        return "Please enter a valid email address"
    err = validate_phone(addr.phone)
    if err:
        return err
    market = countries.get_market(addr.country_code)
    if market is None:
        return "Please choose a valid delivery country"
    if not countries.is_checkout_country(addr.country_code):
        return "Sorry, we can't deliver to that country yet"
    if len(_clean(addr.line1)) < 3:
        return "Please enter your street address"
    if not _clean(addr.city):
        return "Please enter your city"
    rules = market.address_rules
    if rules.state_required and not _clean(addr.admin_area):
        return f"Please enter your {rules.state_label.lower()}"
    return countries.validate_postal(addr.country_code, addr.postal_code)


def street_line(addr: StructuredAddress) -> str:
    parts = [_clean(addr.line1), _clean(addr.line2)]
    return ", ".join(p for p in parts if p)


def to_legacy_string(addr: StructuredAddress) -> str:
    """
    "street, city, state, zip, country" -- exactly 5 comma-separated segments
    as payments._parse_address expects. Commas inside a field are flattened
    to spaces so a field can never shift the segments after it.
    """
    def seg(v: str) -> str:
        return _clean(v).replace(",", " ")
    return ", ".join([
        seg(street_line(addr)), seg(addr.city), seg(addr.admin_area),
        seg(addr.postal_code), addr.country_code.strip().upper(),
    ])


def to_parsed_address(addr: StructuredAddress) -> dict:
    """Shape SilverbeneAdapter.place_order()/get_shipping_methods() already consume."""
    market = countries.get_market(addr.country_code)
    return {
        "line1": street_line(addr),
        "city": _clean(addr.city),
        "state": _clean(addr.admin_area),
        "state_code": _clean(addr.admin_area)[:2].upper(),   # legacy field, unused by the supplier payload
        "postal_code": _clean(addr.postal_code),
        "country_code": market.silverbene_country_id if market else addr.country_code.upper(),
    }


def to_supplier_customer(addr: StructuredAddress) -> dict:
    return {
        "first_name": _clean(addr.first_name),
        "last_name": _clean(addr.last_name),
        "email": ADMIN_SUPPLIER_EMAIL,
        "phone": _clean(addr.phone),
    }
