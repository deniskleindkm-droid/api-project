from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentGoal, AgentLearning, AgentMemory, MonthlyVision
from app.models.order import Order
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())

def set_goal(goal, deadline, metric, target_value):
    with Session(engine) as session:
        existing = session.exec(
            select(AgentGoal).where(AgentGoal.status == "active")
        ).all()
        for g in existing:
            g.status = "superseded"
            session.add(g)

        prompt = f"""You are a business planning AI for BrandDrop, a premium discount sneaker store.

Goal: {goal}
Deadline: {deadline}
Metric: {metric}
Target: {target_value}

Break this goal down into a concrete execution plan. Return JSON:
{{
    "weekly_targets": [
        {{"week": 1, "target": 0, "focus": "what to do this week"}},
        {{"week": 2, "target": 0, "focus": "what to do this week"}},
        {{"week": 3, "target": 0, "focus": "what to do this week"}},
        {{"week": 4, "target": 0, "focus": "what to do this week"}}
    ],
    "required_products": 10,
    "required_marketing_posts": 20,
    "key_strategies": ["strategy1", "strategy2", "strategy3"],
    "risk_factors": ["risk1", "risk2"],
    "agent_instructions": {{
        "market_intelligence": "what to focus on",
        "product_scout": "what to look for",
        "marketing": "what content to create",
        "analytics": "what to measure"
    }}
}}

Return ONLY valid JSON."""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        breakdown = parse_json_response(message.content[0].text)

        new_goal = AgentGoal(
            goal=goal,
            deadline=deadline,
            metric=metric,
            target_value=target_value,
            current_value=0.0,
            status="active",
            breakdown=json.dumps(breakdown)
        )
        session.add(new_goal)
        session.commit()
        session.refresh(new_goal)
        print(f"[Goal Engine] ✅ Goal set: {goal}")
        print(f"[Goal Engine] Plan: {breakdown.get('key_strategies', [])}")
        return new_goal, breakdown

def update_goal_progress():
    with Session(engine) as session:
        goal = session.exec(
            select(AgentGoal).where(AgentGoal.status == "active")
        ).first()

        if not goal:
            return None

        orders = session.exec(select(Order)).all()
        current_revenue = sum(o.total_price for o in orders)

        goal.current_value = current_revenue
        goal.updated_at = datetime.utcnow()

        if current_revenue >= goal.target_value:
            goal.status = "achieved"
            print(f"[Goal Engine] 🎉 GOAL ACHIEVED! ${current_revenue:.2f} / ${goal.target_value:.2f}")
        else:
            progress = (current_revenue / goal.target_value) * 100
            print(f"[Goal Engine] Progress: ${current_revenue:.2f} / ${goal.target_value:.2f} ({progress:.1f}%)")

        session.add(goal)
        session.commit()
        return goal

def reflect_and_learn(agent_name, action, outcome, lesson, metric=None, metric_value=None):
    with Session(engine) as session:
        learning = AgentLearning(
            agent_name=agent_name,
            action_taken=action,
            outcome=outcome,
            metric=metric,
            metric_value=metric_value,
            lesson=lesson,
            apply_to_future=True
        )
        session.add(learning)
        session.commit()
        print(f"[Goal Engine] 📚 {agent_name} learned: {lesson}")

def get_agent_learnings(agent_name):
    with Session(engine) as session:
        learnings = session.exec(
            select(AgentLearning).where(
                AgentLearning.agent_name == agent_name,
                AgentLearning.apply_to_future == True
            ).order_by(AgentLearning.created_at.desc()).limit(10)
        ).all()
        return learnings

def get_active_goal():
    with Session(engine) as session:
        return session.exec(
            select(AgentGoal).where(AgentGoal.status == "active")
        ).first()

def generate_improvement_plan():
    goal = get_active_goal()
    if not goal:
        return None

    with Session(engine) as session:
        learnings = session.exec(
            select(AgentLearning).order_by(AgentLearning.created_at.desc()).limit(20)
        ).all()

        memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()

    learnings_text = "\n".join([
        f"- [{l.agent_name}] {l.action_taken} → {l.outcome}: {l.lesson}"
        for l in learnings
    ]) or "No learnings yet"

    memories_text = "\n".join([
        f"- [{m.agent_name}] {m.memory_type}: {m.content[:80]}"
        for m in memories
    ]) or "No memories yet"

    breakdown = json.loads(goal.breakdown) if goal.breakdown else {}
    progress = (goal.current_value / goal.target_value * 100) if goal.target_value > 0 else 0

    prompt = f"""You are a self-improvement AI for BrandDrop agent system.

Current Goal: {goal.goal}
Progress: ${goal.current_value:.2f} / ${goal.target_value:.2f} ({progress:.1f}%)
Deadline: {goal.deadline}

Past Learnings:
{learnings_text}

Recent Agent Activity:
{memories_text}

Original Strategy:
{json.dumps(breakdown.get('key_strategies', []))}

Based on progress and learnings, generate an improved action plan:
{{
    "assessment": "honest assessment of current progress",
    "what_worked": ["thing1", "thing2"],
    "what_didnt_work": ["thing1", "thing2"],
    "adjusted_strategy": ["new strategy1", "new strategy2", "new strategy3"],
    "immediate_actions": ["do this today1", "do this today2"],
    "agent_adjustments": {{
        "market_intelligence": "adjusted focus",
        "product_scout": "adjusted focus",
        "marketing": "adjusted focus"
    }},
    "confidence": 0.8
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    plan = parse_json_response(message.content[0].text)
    print(f"[Goal Engine] 🧠 Improvement plan generated")
    print(f"[Goal Engine] Assessment: {plan.get('assessment', '')[:100]}")
    print(f"[Goal Engine] Immediate actions: {plan.get('immediate_actions', [])}")
    return plan