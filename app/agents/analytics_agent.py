from dotenv import load_dotenv
load_dotenv()

import json
import os
import anthropic
from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, AgentGoal, MonthlyVision
from app.models.order import Order
from app.models.product import Product
from app.models.content import ProductContent
from app.models.aria_operational import ARIABusinessState

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# DATA COLLECTION
# ============================================================

def get_sales_data():
    """Get real sales data from database."""
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(
            select(Product).where(Product.is_active == True)
        ).all()

        total_revenue = sum(o.total_price for o in orders)
        total_orders = len(orders)

        # Product performance
        product_sales = {}
        for order in orders:
            pid = order.product_id
            if pid not in product_sales:
                product_sales[pid] = {"count": 0, "revenue": 0}
            product_sales[pid]["count"] += order.quantity
            product_sales[pid]["revenue"] += order.total_price

        # Top products
        top_products = []
        for product in products:
            if product.id in product_sales:
                top_products.append({
                    "id": product.id,
                    "name": product.name,
                    "category": product.category,
                    "units_sold": product_sales[product.id]["count"],
                    "revenue": product_sales[product.id]["revenue"],
                    "final_price": product.final_price
                })

        top_products.sort(key=lambda x: x["revenue"], reverse=True)

        # Products with no sales
        no_sales = [
            {"id": p.id, "name": p.name, "category": p.category}
            for p in products
            if p.id not in product_sales
        ]

        return {
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "total_products": len(products),
            "top_products": top_products[:5],
            "no_sales_products": no_sales,
            "product_sales": product_sales
        }


def get_content_performance():
    """Get content posting performance."""
    with Session(engine) as session:
        posted = session.exec(
            select(ProductContent).where(
                ProductContent.status == "posted"
            )
        ).all()

        ready = session.exec(
            select(ProductContent).where(
                ProductContent.status == "ready"
            )
        ).all()

    return {
        "total_posted": len(posted),
        "total_ready": len(ready),
        "by_platform": {
            "instagram": len([p for p in posted if p.platform == "instagram"]),
            "tiktok": len([p for p in posted if p.platform == "tiktok"]),
            "pinterest": len([p for p in posted if p.platform == "pinterest"]),
            "facebook": len([p for p in posted if p.platform == "facebook"])
        },
        "avg_score": sum(p.content_score for p in posted) / len(posted) if posted else 0
    }


def get_goal_progress():
    """Get current goal progress."""
    with Session(engine) as session:
        goal = session.exec(
            select(AgentGoal).where(AgentGoal.status == "active")
        ).first()
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

    return {
        "goal": goal.goal if goal else "No active goal",
        "target": goal.target_value if goal else 0,
        "current": goal.current_value if goal else 0,
        "progress_percent": (goal.current_value / goal.target_value * 100) if goal and goal.target_value > 0 else 0,
        "vision": vision.vision if vision else "No active vision"
    }


# ============================================================
# LEARNING ENGINE
# Updates system based on real performance data
# ============================================================

def update_product_scores_from_sales(sales_data):
    """
    Update product scoring based on real sales.
    Products that sell well get higher future scores.
    Products with no sales get flagged.
    """
    from app.agents.store_config import get_config, set_config

    top_products = sales_data.get("top_products", [])
    no_sales = sales_data.get("no_sales_products", [])

    # Learn which categories perform well
    performing_categories = {}
    for product in top_products:
        cat = product.get("category", "")
        if cat not in performing_categories:
            performing_categories[cat] = 0
        performing_categories[cat] += product.get("revenue", 0)

    if performing_categories:
        best_category = max(performing_categories, key=performing_categories.get)
        set_config(
            "best_performing_category",
            best_category,
            "Category with highest revenue — used to bias product scoring"
        )
        print(f"[Analytics] 📊 Best performing category: {best_category}")

    # Flag no-sales products
    if no_sales:
        no_sales_names = [p["name"][:50] for p in no_sales[:5]]
        print(f"[Analytics] ⚠️ Products with no sales: {no_sales_names}")

        # Signal ARIA about underperforming products
        from app.agents.nervous_system import emit
        emit(
            signal_type="PERFORMANCE_REPORT",
            sender="analytics_agent",
            payload={
                "type": "no_sales_products",
                "products": no_sales_names,
                "recommendation": "Review pricing or remove these products"
            },
            priority=6
        )


def update_business_state(sales_data, content_data, goal_data):
    """Update ARIABusinessState so ARIA always has current picture."""
    with Session(engine) as session:
        # Get existing or create new
        state = session.exec(
            select(ARIABusinessState)
        ).first()

        if not state:
            state = ARIABusinessState()

        state.total_products_live = sales_data.get("total_products", 0)
        state.total_orders = sales_data.get("total_orders", 0)
        state.total_revenue = sales_data.get("total_revenue", 0.0)
        state.top_selling_product = sales_data.get("top_products", [{}])[0].get("name", "") if sales_data.get("top_products") else ""

        # Count uncategorized products
        uncategorized = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.collection_id == None
            )
        ).all()
        state.total_products_uncategorized = len(uncategorized)

        # Count collections
        from app.models.collection import Collection
        collections = session.exec(
            select(Collection).where(Collection.is_active == True)
        ).all()
        state.total_collections = len(collections)

        # System health
        if sales_data.get("total_orders", 0) > 0:
            state.system_health = "green"
        elif sales_data.get("total_products", 0) > 0:
            state.system_health = "yellow"
        else:
            state.system_health = "red"

        state.updated_at = datetime.utcnow()
        session.add(state)
        session.commit()
        print(f"[Analytics] ✅ Business state updated — health: {state.system_health}")


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_intelligence_report(sales_data, content_data, goal_data):
    """Generate ARIA-level intelligence report."""
    try:
        prompt = f"""You are the Analytics Agent for Mikisi — a women's beauty accessories store.

Current business data:
- Total Revenue: ${sales_data['total_revenue']:.2f}
- Total Orders: {sales_data['total_orders']}
- Active Products: {sales_data['total_products']}
- Top Products: {json.dumps(sales_data['top_products'][:3])}
- Products with no sales: {len(sales_data['no_sales_products'])}
- Goal Progress: {goal_data['progress_percent']:.1f}% of {goal_data['goal']}
- Content Posted: {content_data['total_posted']}
- Content Ready: {content_data['total_ready']}

Generate an intelligence report as JSON:
{{
    "summary": "2-3 sentence executive summary",
    "performance": "excellent/good/average/poor",
    "top_insight": "most important thing happening right now",
    "revenue_trend": "growing/stable/declining",
    "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"],
    "products_to_add": ["product keyword 1", "product keyword 2"],
    "products_to_remove": ["underperforming product names"],
    "alert_level": "green/yellow/red",
    "alert_reason": "why this alert level"
}}

Return ONLY valid JSON."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        return json.loads(text.strip())

    except Exception as e:
        print(f"[Analytics] Report generation error: {e}")
        return None


def save_report(report):
    """Save report to agent memory."""
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="analytics_agent",
            memory_type="report",
            content=json.dumps(report),
            confidence=0.9
        )
        session.add(memory)
        session.commit()


# ============================================================
# MAIN ANALYTICS AGENT
# ============================================================

def run_analytics_agent():
    """
    Main analytics agent.
    Collects data, learns from it, updates system, reports to ARIA.
    Runs every 6 hours from scheduler.
    """
    print(f"[Analytics] 📊 Running analytics agent...")

    # Collect data
    sales_data = get_sales_data()
    content_data = get_content_performance()
    goal_data = get_goal_progress()

    print(f"[Analytics] Revenue: ${sales_data['total_revenue']:.2f} | Orders: {sales_data['total_orders']} | Products: {sales_data['total_products']}")

    # Learn from data
    update_product_scores_from_sales(sales_data)

    # Update business state
    update_business_state(sales_data, content_data, goal_data)

    # Generate report
    report = generate_intelligence_report(sales_data, content_data, goal_data)

    if report:
        save_report(report)
        print(f"[Analytics] Performance: {report.get('performance')}")
        print(f"[Analytics] Alert: {report.get('alert_level')} — {report.get('alert_reason')}")
        print(f"[Analytics] Top insight: {report.get('top_insight')}")

        # Signal ARIA with report
        from app.agents.nervous_system import emit
        emit(
            signal_type="PERFORMANCE_REPORT",
            sender="analytics_agent",
            payload={
                "type": "full_report",
                "performance": report.get("performance"),
                "alert_level": report.get("alert_level"),
                "top_insight": report.get("top_insight"),
                "revenue": sales_data["total_revenue"],
                "orders": sales_data["total_orders"]
            },
            priority=6
        )

    print(f"[Analytics] ✅ Analytics complete")
    return report


def run_analytics():
    """Backward compatible wrapper — called by existing scheduler."""
    return run_analytics_agent()