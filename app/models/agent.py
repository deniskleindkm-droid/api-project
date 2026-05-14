from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class AgentMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str
    memory_type: str
    content: str
    source: Optional[str] = None
    confidence: float = 0.0
    acted_on: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_agent: str
    to_agent: str
    task_type: str
    payload: str
    status: str = "pending"
    result: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

class MarketInsight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str
    topic: str
    sentiment: str
    demand_signal: str
    target_demographic: Optional[str] = None
    location_signal: Optional[str] = None
    product_keywords: str
    raw_data: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MonthlyVision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    month: str
    vision: str
    target_market: str
    target_products: str
    target_locations: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentLearning(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str
    action_taken: str
    outcome: str
    metric: Optional[str] = None
    metric_value: Optional[float] = None
    lesson: str
    apply_to_future: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentGoal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    goal: str
    deadline: str
    metric: str
    target_value: float
    current_value: float = 0.0
    status: str = "active"
    breakdown: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)