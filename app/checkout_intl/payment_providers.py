"""
Payment-provider contract (foundation only -- Stage 1).

Separates three things that must never be conflated:
  1. customer -> Mikisi payment (this module): provider + presentment currency
     + payment methods;
  2. Mikisi -> Silverbene supplier settlement (USD, owner-handled; Silverbene's
     pay link is never given to a customer -- see SilverbeneAdapter.place_order);
  3. Mikisi product pricing (frozen this stage; nothing here touches prices).

StripeProvider reproduces the legacy Checkout Session exactly: USD, card
payment method type (Apple Pay / Google Pay / Link surface through Stripe's
card wallet support inside Checkout), line items at product.final_price. It
declares capabilities so later stages can widen methods and currencies
without touching checkout code. PayPal lives in paypal.py (flag INTL_PAYPAL,
sandbox by default) with its own capture/webhook/idempotency path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

SUPPLIER_SETTLEMENT_CURRENCY = "USD"


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    enabled: bool
    presentment_currencies: List[str] = field(default_factory=list)
    payment_method_types: List[str] = field(default_factory=list)
    wallets: List[str] = field(default_factory=list)          # surfaced by the provider, not separate integrations
    notes: str = ""


class PaymentProvider(Protocol):
    capabilities: ProviderCapabilities

    def create_session(self, *, line_items: list, success_url: str, cancel_url: str,
                       customer_email: str, metadata: dict): ...


def stripe_dynamic_methods_enabled() -> bool:
    import os
    return os.getenv("INTL_STRIPE_DYNAMIC_METHODS", "").strip().lower() in {"1", "true", "yes", "on"}


class StripeProvider:
    """
    Default: legacy-identical (payment_method_types=["card"]). With
    INTL_STRIPE_DYNAMIC_METHODS on, payment_method_types is OMITTED so Stripe
    Checkout selects eligible methods (cards, Apple Pay, Google Pay, Link, regional
    methods) from the account's Dashboard settings and the customer's
    location/currency -- we do not hand-encode regional methods.
    """
    def __init__(self, dynamic: Optional[bool] = None):
        self.dynamic = stripe_dynamic_methods_enabled() if dynamic is None else dynamic

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="stripe", enabled=True,
            presentment_currencies=["USD"],            # widened in the pricing/currency stage
            payment_method_types=[] if self.dynamic else ["card"],
            wallets=["apple_pay", "google_pay", "link"],
            notes=("dynamic payment methods (Dashboard-managed)" if self.dynamic
                   else "legacy card-only; wallets surface inside Checkout's card method where eligible"),
        )

    def create_session(self, *, line_items, success_url, cancel_url, customer_email, metadata):
        import stripe
        kwargs = dict(line_items=line_items, mode="payment", success_url=success_url,
                      cancel_url=cancel_url, customer_email=customer_email, metadata=metadata)
        if not self.dynamic:
            kwargs["payment_method_types"] = ["card"]
        return stripe.checkout.Session.create(**kwargs)


def get_provider(name: str = "stripe"):
    if name == "stripe":
        return StripeProvider()
    if name == "paypal":
        from app.checkout_intl import paypal
        if not paypal.paypal_enabled():
            raise ValueError("payment provider 'paypal' is not available")
        return paypal.PayPalProvider()
    raise ValueError(f"payment provider '{name}' is not available")
