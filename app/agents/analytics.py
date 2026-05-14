from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision
from app.models.product import Product
from app.models.order import Order

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_sales_data():
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(select(Product)).all()

        total_orders = len(orders)
        total_revenue = sum(o.total_price for o in orders)

        product_sales = {}
        for order in orders:
            pid = order.product_id
            if pid not in product_sales:
                product_sales[pid] = {"count": 0, "revenue": 0}
            product_sales[pid]["count"] += order.quantity
            product_sales[pid]["revenue"] += order.total_price

        top_products = []
        for product in products:
            if product.id in product_sales:
                top_products.append({
                    "name": product.name,
                    "brand": product.brand,
                    "units_sold": product_sales[product.id]["count"],
                    "revenue": product_sales[product.id]["revenue"]
                })

        top_products.sort(key=lambda x: x["revenue"], reverse=True)

        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_products": len(products),
            "top_products": top_products[:5],
            "low_stock": [{"name": p.name, "stock": p.stock} for p in products if p.stock < 20]
        }

def get_agent_memories():
    with Session(engine) as session:
        memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()
        return memories

def get_recent_insights():
    with Session(engine) as session:
        return session.exec(
            select(MarketInsight).order_by(MarketInsight.created_at.desc()).limit(10)
        ).all()

def save_memory(content, memory_type, confidence):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="analytics",
            memory_type=memory_type,
            content=content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def create_task_for_market_intelligence(feedback):
    with Session(engine) as session:
        task = AgentTask(
            from_agent="analytics",
            to_agent="market_intelligence",
            task_type="analyze",
            payload=json.dumps(feedback)
        )
        session.add(task)
        session.commit()

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())

def generate_report():
    sales = get_sales_data()
    memories = get_agent_memories()
    insights = get_recent_insights()

    vision = None
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

    vision_context = f"Monthly vision: {vision.vision}\nTarget market: {vision.target_market}" if vision else "No active vision"

    agent_activity = "\n".join([
        f"- [{m.agent_name}] {m.memory_type}: {m.content[:100]}"
        for m in memories
    ])

    market_signals = "\n".join([
        f"- {i.platform}: {i.topic} ({i.demand_signal} demand)"
        for i in insights
    ])

    prompt = f"""You are an Analytics Agent for BrandDrop e-commerce store.

{vision_context}

Current Sales Data:
- Total Orders: {sales['total_orders']}
- Total Revenue: ${sales['total_revenue']:.2f}
- Total Products: {sales['total_products']}
- Top Products: {json.dumps(sales['top_products'], indent=2)}
- Low Stock Items: {json.dumps(sales['low_stock'], indent=2)}

Recent Agent Activity:
{agent_activity}

Recent Market Signals:
{market_signals}

Generate a report as JSON:
{{
    "summary": "2-3 sentence executive summary",
    "performance": "good/average/poor",
    "top_insight": "most important thing happening right now",
    "revenue_trend": "growing/stable/declining",
    "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"],
    "products_to_add": ["product keyword 1", "product keyword 2"],
    "products_to_remove": ["low performing product names"],
    "market_opportunities": ["opportunity 1", "opportunity 2"],
    "feedback_for_scout": "what the product scout should look for next",
    "alert_level": "green/yellow/red",
    "alert_reason": "why this alert level"
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return parse_json_response(message.content[0].text)

def run_analytics():
    print("[Analytics Agent] Generating report...")

    try:
        report = generate_report()

        save_memory(
            content=json.dumps(report),
            memory_type="report",
            confidence=0.9
        )

        if report.get("products_to_add"):
            create_task_for_market_intelligence({
                "action": "scout_these",
                "keywords": report.get("products_to_add", []),
                "market_opportunities": report.get("market_opportunities", []),
                "feedback": report.get("feedback_for_scout", "")
            })

        print(f"[Analytics Agent] ✅ Report generated")
        print(f"[Analytics Agent] Performance: {report.get('performance')}")
        print(f"[Analytics Agent] Alert: {report.get('alert_level')} — {report.get('alert_reason')}")
        print(f"[Analytics Agent] Top insight: {report.get('top_insight')}")
        print(f"[Analytics Agent] Summary: {report.get('summary')}")

        return report

    except Exception as e:
        print(f"[Analytics Agent] Error: {e}")
        return None