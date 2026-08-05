from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    product_id: int = Field(foreign_key="product.id")
    quantity: int = 1
    total_price: float
    status: str = "pending"
    shipping_address: str = ""
    shipping_method: Optional[str] = None   # "fast_track" or "usps"
    tracking_number: Optional[str] = None
    supplier_notified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    guest_email: Optional[str] = None
    is_guest: bool = False
    # The canonical internal variant identity (see app.models.product_variant.
    # ProductVariant) — carried over from the CartItem at checkout time so
    # order recovery/retry can always resolve the customer's real selection
    # instead of falling back to the product's default/first variant. NULL on
    # orders placed before this column existed.
    variant_id: Optional[int] = Field(default=None, foreign_key="product_variant.id")
    # The Stripe Checkout Session id (e.g. "cs_..."). Stripe explicitly warns
    # webhook events can be delivered more than once (retries on timeout/non-2xx,
    # or just duplicate delivery under normal operation) — this is the
    # idempotency key process_order_background() checks before creating any
    # orders for a session, so a duplicate delivery (or the admin recover-order
    # endpoint firing after the webhook already succeeded) can never double-
    # charge Silverbene or double-decrement stock. NULL on orders placed before
    # this column existed.
    stripe_session_id: Optional[str] = Field(default=None, index=True)

class OrderTracking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    cj_order_id: str
    supplier_name: str = Field(default="CJDropshipping")
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    status: str = Field(default="pending")
    last_checked: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    shipping_notified: bool = Field(default=False)
    delivery_notified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Real per-order supplier cost detail, captured at place_order() time —
    # Dennis needs this for tax/bookkeeping (COGS + shipping expense per
    # order); Silverbene has no order-detail API to look this up after the
    # fact (confirmed 2026-08-01, every candidate endpoint 404s), so this is
    # the only durable record of what was actually paid, not what the
    # customer paid or what the catalog assumes.
    supplier_product_cost:    Optional[float] = None   # wholesale cost of the item(s) at order time
    supplier_shipping_cost:   Optional[float] = None   # real cheapest-carrier cost place_order() selected
    supplier_shipping_carrier: Optional[str] = None    # e.g. "USPS(8-10 workdays...)"
    supplier_total_charged:   Optional[float] = None   # amount_due/total_price from Silverbene's response, if present
    supplier_currency:        Optional[str] = None
    supplier_raw_response:    Optional[str] = None     # full JSON dump of create_order's response — complete audit trail

    # Delivery-preference relay (see silverbene_shipping_monitor / dhl_monitor) —
    # lets the customer tell Mikisi (not DHL) where to leave the package, since
    # DHL's own "On Demand Delivery" portal link goes to hello@mikisi.co, never
    # the customer directly (see project_customer_phone_not_masked_decision memory).
    delivery_preference:           Optional[str] = None   # customer's stated instruction, extracted from their reply
    delivery_preference_requested: bool = Field(default=False)
    dhl_odd_link:                  Optional[str] = None   # DHL's On Demand Delivery portal link for this waybill
    delivery_alert_sent:           bool = Field(default=False)

    # Shipping-delay alert dedup -- check_for_delays() re-runs every 6h tracking
    # cycle; without this, a genuinely slow order (see order #21, 2026-08-05:
    # 12+ days and still hadn't left China) would re-emit ORDER_DELAYED every
    # cycle once the underlying bug that made this silent was fixed.
    delay_alerted: bool = Field(default=False)