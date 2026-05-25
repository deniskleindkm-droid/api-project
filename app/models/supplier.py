from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Supplier(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    adapter_class: str
    base_url: str
    api_key_env: str
    is_active: bool = Field(default=True)
    supported_categories: Optional[str] = None
    supported_countries: Optional[str] = None
    reliability_score: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)