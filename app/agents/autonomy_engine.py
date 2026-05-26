from sqlmodel import Session, select
from app.database import engine
from app.models.autonomy import AutonomyRule
from app.agents.nervous_system import emit


def check_autonomy(agent: str, action: str, context: dict) -> dict:
    """
    Check if an agent can act autonomously or must signal.
    
    Usage:
        result = check_autonomy("product_agent", "import_product", {"total_score": 0.72})
        if result["autonomous"]:
            # do it alone
        else:
            # emit signal to result["signal_to"]
    
    Returns:
        {
            "autonomous": True/False,
            "signal_to": "aria" or "dennis" or None,
            "priority": 1-10,
            "rule": the matching rule description
        }
    """
    with Session(engine) as session:
        rules = session.exec(
            select(AutonomyRule).where(
                AutonomyRule.agent == agent,
                AutonomyRule.action == action,
                AutonomyRule.is_active == True
            )
        ).all()

    if not rules:
        # No rule found — default to signal ARIA
        print(f"[Autonomy] No rule for {agent}.{action} — defaulting to signal ARIA")
        return {
            "autonomous": False,
            "signal_to": "aria",
            "priority": 5,
            "rule": "default — no rule found"
        }

    # Find the matching rule based on condition
    for rule in rules:
        field_value = context.get(rule.condition_field)
        if field_value is None:
            continue

        matched = False
        if rule.condition_operator == "gte" and field_value >= rule.condition_value:
            matched = True
        elif rule.condition_operator == "gt" and field_value > rule.condition_value:
            matched = True
        elif rule.condition_operator == "lte" and field_value <= rule.condition_value:
            matched = True
        elif rule.condition_operator == "lt" and field_value < rule.condition_value:
            matched = True
        elif rule.condition_operator == "eq" and field_value == rule.condition_value:
            matched = True

        if matched:
            print(f"[Autonomy] Rule matched: {rule.description}")
            return {
                "autonomous": rule.autonomous,
                "signal_to": rule.signal_to,
                "priority": rule.priority,
                "rule": rule.description
            }

    # No condition matched — default to signal ARIA
    print(f"[Autonomy] No condition matched for {agent}.{action} — defaulting to signal ARIA")
    return {
        "autonomous": False,
        "signal_to": "aria",
        "priority": 5,
        "rule": "default — no condition matched"
    }


def can_act(agent: str, action: str, context: dict) -> bool:
    """Simple boolean check — can this agent act autonomously?"""
    result = check_autonomy(agent, action, context)
    return result["autonomous"]


def get_all_rules():
    """Get all active autonomy rules — for dashboard display."""
    with Session(engine) as session:
        rules = session.exec(
            select(AutonomyRule).where(AutonomyRule.is_active == True)
            .order_by(AutonomyRule.agent, AutonomyRule.action)
        ).all()
    return rules


def add_rule(agent, action, condition_field, condition_operator, 
             condition_value, autonomous, signal_to=None, priority=5, description=""):
    """
    Add a new autonomy rule dynamically.
    Called by ARIA or Dennis when new agents are added.
    No hardcoding — rules live in database.
    """
    with Session(engine) as session:
        rule = AutonomyRule(
            agent=agent,
            action=action,
            condition_field=condition_field,
            condition_operator=condition_operator,
            condition_value=condition_value,
            autonomous=autonomous,
            signal_to=signal_to,
            priority=priority,
            description=description,
            is_active=True
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        print(f"[Autonomy] ✅ New rule added: {agent}.{action} — {description}")
        return rule