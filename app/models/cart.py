from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class CartItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    product_id: int = Field(foreign_key="product.id")
    quantity: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)