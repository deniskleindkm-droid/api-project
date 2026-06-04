from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Collection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, foreign_key="collection.id")
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    video_url: Optional[str] = None