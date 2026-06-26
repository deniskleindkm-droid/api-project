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