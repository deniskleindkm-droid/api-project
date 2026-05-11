from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    brand: str
    category: str
    description: str
    price: float
    discount: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    stock: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)