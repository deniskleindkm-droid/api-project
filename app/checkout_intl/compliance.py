"""
Market compliance policy -- versioned data, not constants.

"Supplier can ship there" and "Mikisi may sell there" are different questions.
This module answers the second one. It ships EMPTY on purpose: no market is
blocked by an unsourced assumption baked into checkout code. Each restriction
must carry provenance, so a block can be audited, reviewed and expired:

    country         ISO alpha-2
    action          "block"
    jurisdiction    whose rule it is (e.g. "US-OFAC", "Stripe", "PayPal", "Mikisi-policy")
    source          URL or document reference
    reason          why
    effective_from  ISO date the restriction starts applying
    review_date     ISO date by which a human must re-confirm it
    effective_until optional ISO date it stops applying

Restrictions live in compliance_policy.json beside this file. A malformed
entry raises at load time rather than silently doing nothing -- a restriction
that fails to parse must never fail open.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

POLICY_PATH = os.path.join(os.path.dirname(__file__), "compliance_policy.json")
_REQUIRED = ("country", "action", "jurisdiction", "source", "reason", "effective_from", "review_date")


@dataclass(frozen=True)
class MarketRestriction:
    country: str
    action: str
    jurisdiction: str
    source: str
    reason: str
    effective_from: date
    review_date: date
    effective_until: Optional[date] = None

    def active_on(self, today: date) -> bool:
        return self.effective_from <= today and (self.effective_until is None or today < self.effective_until)


def parse_restriction(raw: dict) -> MarketRestriction:
    missing = [k for k in _REQUIRED if not str(raw.get(k, "")).strip()]
    if missing:
        raise ValueError(f"compliance restriction for {raw.get('country')!r} missing provenance: {missing}")
    if raw["action"] != "block":
        raise ValueError(f"unsupported compliance action {raw['action']!r}")
    return MarketRestriction(
        country=raw["country"].strip().upper(), action=raw["action"], jurisdiction=raw["jurisdiction"],
        source=raw["source"], reason=raw["reason"],
        effective_from=date.fromisoformat(raw["effective_from"]),
        review_date=date.fromisoformat(raw["review_date"]),
        effective_until=date.fromisoformat(raw["effective_until"]) if raw.get("effective_until") else None,
    )


def load_restrictions(path: str = POLICY_PATH) -> List[MarketRestriction]:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return []
    return [parse_restriction(r) for r in doc.get("restrictions", [])]


def blocking_restriction(country: str, today: Optional[date] = None,
                         restrictions: Optional[List[MarketRestriction]] = None) -> Optional[MarketRestriction]:
    today = today or date.today()
    restrictions = load_restrictions() if restrictions is None else restrictions
    return next((r for r in restrictions
                 if r.country == country.upper() and r.action == "block" and r.active_on(today)), None)


def is_blocked(country: str, today: Optional[date] = None) -> bool:
    return blocking_restriction(country, today) is not None


def overdue_reviews(today: Optional[date] = None) -> List[MarketRestriction]:
    """Restrictions whose review_date has passed -- for a scheduled reminder."""
    today = today or date.today()
    return [r for r in load_restrictions() if r.review_date < today]
