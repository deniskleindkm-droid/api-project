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
    created_at: datetime = Field(default_factory=datetime.utcnow)