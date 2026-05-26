from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class StoreConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str
    value: str
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)