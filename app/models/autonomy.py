from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class AutonomyRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent: str                          # which agent this rule applies to
    action: str                         # what action
    condition_field: str                # what field to check
    condition_operator: str             # gt, lt, eq, gte, lte
    condition_value: float              # threshold value
    autonomous: bool                    # True = act alone, False = signal
    signal_to: Optional[str] = None    # who to signal if not autonomous
    priority: int = Field(default=5)   # signal priority 1=critical
    description: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductScore(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    supplier_product_id: str
    supplier_name: str
    product_name: str
    category: str
    cost_price: float
    image_url: Optional[str] = None
    supplier_rating: float = Field(default=0.0)
    order_volume_score: float = Field(default=0.0)
    trend_score: float = Field(default=0.0)
    visual_score: float = Field(default=0.5)
    price_score: float = Field(default=0.5)
    total_score: float = Field(default=0.0)
    recommendation: str = Field(default="review")  # auto_import, review, reject
    scored_at: datetime = Field(default_factory=datetime.utcnow)