from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class InstagramPost(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    post_type: str                            # "product" | "campaign"
    image_url: str
    caption: str
    hashtags: str
    instagram_post_id: Optional[str] = None  # returned by Instagram Graph API after posting
    # Engagement — populated 24h after posting by pull_engagement()
    likes: int = 0
    comments: int = 0
    saves: int = 0
    shares: int = 0
    reach: int = 0
    engagement_score: float = 0.0            # (likes + comments*2 + saves*3 + shares*3) / reach * 100
    engagement_pulled_at: Optional[datetime] = None
    posted_at: datetime = Field(default_factory=datetime.utcnow)
