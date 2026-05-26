from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class ARIAActionLedger(SQLModel, table=True):
    """
    Tracks every business-level action ARIA commits to.
    ARIA can only say 'done' when status is verified_success.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[str] = None
    requested_by: str = "dennis"
    assigned_agent: str
    action_type: str
    input_summary: str
    status: str = Field(default="planned")
    # Status flow: planned → executing → executed_unverified → verified_success / failed / blocked
    result_summary: Optional[str] = None
    verification_status: Optional[str] = None
    verification_evidence: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls_used: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ARIATool(SQLModel, table=True):
    """
    Tool registry — ARIA discovers her capabilities from this table.
    No hardcoding. New tools register here, ARIA finds them dynamically.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str
    agent: str
    adapter_key: str
    input_schema: Optional[str] = None
    output_schema: Optional[str] = None
    risk_level: str = Field(default="low")  # low, medium, high, critical
    requires_confirmation: bool = False
    verification_method: Optional[str] = None
    rollback_method: Optional[str] = None
    timeout_ms: int = Field(default=30000)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ARIAConversationState(SQLModel, table=True):
    """
    Working memory per conversation.
    ARIA remembers what happened in this conversation.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str
    last_search_results: Optional[str] = None  # JSON — last CJ search
    last_action_taken: Optional[str] = None
    last_tool_called: Optional[str] = None
    pending_actions: Optional[str] = None  # JSON list
    commitments_made: Optional[str] = None  # JSON — what ARIA promised
    current_intent: Optional[str] = None
    context_summary: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ARIABusinessState(SQLModel, table=True):
    """
    Live snapshot of business health.
    ARIA reads this to understand the current state of Mikisi.
    Updated by analytics agent regularly.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    total_products_live: int = 0
    total_products_uncategorized: int = 0
    total_collections: int = 0
    total_orders: int = 0
    total_revenue: float = 0.0
    top_selling_product: Optional[str] = None
    products_missing_images: int = 0
    products_missing_collection: int = 0
    active_suppliers: int = 0
    last_product_imported: Optional[str] = None
    last_order_placed: Optional[str] = None
    system_health: str = Field(default="green")  # green, yellow, red
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ARIAPolicy(SQLModel, table=True):
    """
    Policy engine — defines what each agent can do alone vs needs approval.
    No hardcoding. Rules live here, enforced by autonomy engine.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    action_type: str
    risk_level: str  # low, medium, high, critical
    allowed_agents: str  # comma separated
    requires_human_approval: bool = False
    requires_aria_approval: bool = False
    max_allowed_amount: Optional[float] = None
    rollback_required: bool = False
    description: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)