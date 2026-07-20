from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class CartItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    product_id: int = Field(foreign_key="product.id")
    quantity: int = 1
    selected_size: Optional[str] = None
    selected_color: Optional[str] = None
    # The exact Silverbene option_id the frontend resolved when the customer made
    # this selection (from /variant-prices, which is built from real priced options).
    # Carried straight through to checkout so we never have to re-guess it from
    # selected_size/selected_color text at order time.
    selected_option_id: Optional[str] = None
    # The canonical internal variant identity (see app.models.product_variant.
    # ProductVariant) — the primary field going forward. selected_size/color/
    # option_id above are kept for display and as a same-deploy-cycle fallback
    # while the frontend transition completes.
    variant_id: Optional[int] = Field(default=None, foreign_key="product_variant.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)