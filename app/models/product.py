from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ProductCreate(SQLModel):
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7