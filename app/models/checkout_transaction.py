from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class CheckoutTransaction(SQLModel, table=True):
    """
    Locked record of everything the customer agreed to BEFORE paying, for the
    international checkout (Stage 1, behind INTL_CHECKOUT flag -- see
    app/checkout_intl). Payment and fulfillment read only from here, so
    fulfillment never re-decides the shipping method or re-parses an address.

    Statuses: quoting -> quoted | unavailable -> locked -> paid -> (fulfilled | needs_attention | refunded).
    JSON columns are stored as text for SQLite/Postgres parity with the
    rest of this schema.
    """
    id: str = Field(primary_key=True)                 # uuid4 hex; also Stripe metadata "checkout_id"
    status: str = Field(default="quoted", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    user_email: Optional[str] = None                  # account email or guest email
    is_guest: bool = False
    first_name: str = ""
    last_name: str = ""

    country_code: str = ""                            # ISO 3166-1 alpha-2
    supplier_country_id: str = ""                     # what Silverbene's country_id gets
    address_json: str = "{}"                          # full structured address as collected by Mikisi
    supplier_address_json: str = "{}"                 # the minimal subset actually sent to Silverbene

    items_json: str = "[]"                            # validated lines incl. resolved supplier option_id
    quote_json: str = "{}"                            # normalized Silverbene rate snapshot (internal costs included)
    quote_fetched_at: Optional[datetime] = None
    quote_expires_at: Optional[datetime] = None
    quote_error: Optional[str] = None                 # supplier failure detail when quoting could not complete
    ack_json: Optional[str] = None                    # what the customer last SAW: {tier: {method_id, price}}
    quote_error: Optional[str] = None                 # supplier failure detail when quoting could not complete
    ack_json: Optional[str] = None                    # what the customer last SAW: {tier: {method_id, price}}

    shipping_method_id: Optional[str] = None          # exact Silverbene "way" chosen by the customer
    shipping_method_name: Optional[str] = None
    shipping_eta: Optional[str] = None
    shipping_resolved_json: Optional[str] = None      # the REAL supplier method picked after payment for a class choice
    shipping_tier: Optional[str] = None               # STANDARD | EXPRESS (customer-facing service tier)
    shipping_customer_price: Optional[float] = None   # what the customer pays for the chosen delivery (0 = included)
    shipping_supplier_price: Optional[float] = None   # supplier cost snapshot (internal; never shown to customers)

    # Customer -> Mikisi payment layer. Deliberately separate from the
    # Mikisi -> Silverbene settlement layer below.
    presentment_currency: str = "USD"
    payment_provider: str = "stripe"
    payment_ref: Optional[str] = None                 # Stripe checkout session id, or "pp_<PayPal order id>"
    payment_capture_id: Optional[str] = None          # PayPal capture id (needed for refunds)
    payment_attempts: int = 0                         # provider sessions/orders created for this checkout
    # Mikisi -> Silverbene settlement layer. Silverbene's pay link is USD
    # and is only ever handled by the owner alert path, never customers.
    supplier_settlement_currency: str = "USD"

    feature_version: str = "intl-stage1"
