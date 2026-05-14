from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class AgentMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str
    memory_type: str  # insight, product, trend, alert, task
    content: str
    source: Optional[str] = None
    confidence: float = 0.0  # 0-1 how confident the agent is
    acted_on: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_agent: str
    to_agent: str
    task_type: str  # scout, analyze, add_product, market, report
    payload: str  # JSON string
    status: str = "pending"  # pending, running, done, failed
    result: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

class MarketInsight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str  # reddit, twitter, tiktok, web
    topic: str
    sentiment: str  # positive, negative, neutral
    demand_signal: str  # high, medium, low
    target_demographic: Optional[str] = None
    location_signal: Optional[str] = None
    product_keywords: str  # comma separated
    raw_data: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MonthlyVision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    month: str  # e.g. "2026-05"
    vision: str  # your monthly goal
    target_market: str
    target_products: str
    target_locations: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)