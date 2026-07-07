from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class OrderVariantCheck(SQLModel, table=True):
    """
    One record per order line item — tracks the full variant verification chain.

    Stage 1 (immediate, local):
      Confirm the option_id we sent maps to the size+color the customer chose.
      This runs inside the Stripe webhook before returning to the customer.

    Stage 2 (deferred, Silverbene-side):
      Silverbene has no order query API (all 404 as of 2026-07-06).
      When Silverbene ships and emails hello@mikisi.co, the shipping monitor
      sets silverbene_confirmed=True — proving they at least processed the order.
      Full variant confirmation on their side requires manual review or future API.

    match_status values:
      ok             — option_id maps exactly to customer's size+color
      size_mismatch  — color matched but wrong size was routed
      color_mismatch — size matched but wrong color was routed
      both_mismatch  — neither size nor color matched
      fallback_used  — customer selected size/color but resolve fell to first variant
      not_found      — option_id not present in our variants JSON (DB stale)
      no_variants    — product has no variant data at all
    """
    __tablename__ = "order_variant_check"

    id:                    int           = Field(default=None, primary_key=True)
    order_id:              int           = Field(index=True)   # Mikisi DB order ID
    silverbene_order_id:   Optional[str] = None                # Silverbene's ref from place_order()

    product_id:            int
    product_name:          str

    customer_email:        Optional[str] = None
    customer_name:         Optional[str] = None

    # What the customer actually selected (display values from cart)
    selected_size:         Optional[str] = None
    selected_color:        Optional[str] = None

    # The option_id resolved by resolve_option_id() and sent to Silverbene
    option_id_sent:        Optional[str] = None
    # Which pass of resolve_option_id() produced this: exact|size_only|color_only|fallback
    resolve_pass:          Optional[str] = None

    # What that option_id actually maps to in our variants DB
    variant_size:          Optional[str] = None
    variant_color:         Optional[str] = None

    match_status:          str           = "ok"
    mismatch_detail:       Optional[str] = None

    # Stage 2: set True by shipping monitor when Silverbene shipping email is received
    silverbene_confirmed:  bool          = False
    silverbene_confirmed_at: Optional[datetime] = None

    alerted:               bool          = False   # Dennis was emailed about a problem
    checked_at:            datetime      = Field(default_factory=datetime.utcnow)
