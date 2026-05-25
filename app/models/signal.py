from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
import json

class SystemSignal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    signal_type: str
    sender: str
    receiver: Optional[str] = None  # None means broadcast to all
    payload: Optional[str] = None   # JSON string
    priority: int = Field(default=5)  # 1=critical, 10=routine
    status: str = Field(default="pending")  # pending, processed, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None