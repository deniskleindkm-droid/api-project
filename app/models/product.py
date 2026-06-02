from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

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
    images: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    collection_id: Optional[int] = Field(default=None, foreign_key="collection.id")
    cj_product_id: Optional[str] = None
    cj_sku: Optional[str] = None
    variants: Optional[str] = Field(default=None)
    # Silverbene-specific fields — read directly by the storefront
    material: Optional[str] = None          # e.g. "925 Sterling Silver", "18k Gold Plated"
    sizes: Optional[str] = None             # JSON array: ["6","6.5","7","7.5","8"] or ["16\"","18\"","20\""]
    colors: Optional[str] = None            # JSON array: ["gold","rose gold","silver"]

class ProductCreate(SQLModel):
    name: str
    brand: str
    category: str
    description: str
    original_price: float
    discount_percent: float = 0.0
    final_price: float
    image_url: Optional[str] = None
    images: Optional[str] = None
    stock: int = 0
    supplier_name: Optional[str] = None
    supplier_url: Optional[str] = None
    shipping_days: int = 7
    cj_product_id: Optional[str] = None
    cj_sku: Optional[str] = None
    material: Optional[str] = None
    sizes: Optional[str] = None
    colors: Optional[str] = None