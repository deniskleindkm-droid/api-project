from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class PlatformAnalytics(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str                          # pinterest, instagram, tiktok, facebook
    post_id: Optional[str] = None          # pin_id, reel_id, etc.
    product_id: Optional[int] = None       # product.id — nullable (account-level rows)
    date: str                              # YYYY-MM-DD
    impressions: int = 0
    saves: int = 0
    clicks: int = 0
    outbound_clicks: int = 0
    engagement_rate: float = 0.0
    raw_data: Optional[str] = None         # full API response, JSON string
    created_at: datetime = Field(default_factory=datetime.utcnow)
