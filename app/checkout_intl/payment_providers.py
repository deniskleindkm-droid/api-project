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
without touching checkout code. PayPalProvider is a declared-but-disabled
slot: a real integration needs its own webhook + idempotency path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol

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


class StripeProvider:
    capabilities = ProviderCapabilities(
        name="stripe",
        enabled=True,
        presentment_currencies=["USD"],                 # widened in the pricing/currency stage
        payment_method_types=["card"],
        wallets=["apple_pay", "google_pay", "link"],    # available within Checkout's card method where eligible
        notes="Legacy-identical parameters; regional methods require the currency stage.",
    )

    def create_session(self, *, line_items, success_url, cancel_url, customer_email, metadata):
        import stripe
        return stripe.checkout.Session.create(
            payment_method_types=list(self.capabilities.payment_method_types),
            line_items=line_items,
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata=metadata,
        )


class PayPalProvider:
    capabilities = ProviderCapabilities(
        name="paypal", enabled=False,
        notes="Not implemented. Needs its own order/capture webhook and idempotency keyed to CheckoutTransaction.id.",
    )

    def create_session(self, **_):
        raise NotImplementedError("PayPal is not enabled")


PROVIDERS = {"stripe": StripeProvider(), "paypal": PayPalProvider()}


def get_provider(name: str = "stripe"):
    p = PROVIDERS.get(name)
    if p is None or not p.capabilities.enabled:
        raise ValueError(f"payment provider '{name}' is not available")
    return p
