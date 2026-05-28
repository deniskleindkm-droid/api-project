from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class ProductContent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    platform: str  # instagram, tiktok, pinterest, facebook
    caption: Optional[str] = None
    hook: Optional[str] = None  # first 3 seconds for video
    hashtags: Optional[str] = None
    emotional_angle: Optional[str] = None
    content_score: float = Field(default=0.0)
    status: str = Field(default="ready")  # ready, posted, failed
    posted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)