from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, AgentTask, MonthlyVision
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_pending_tasks():
    with Session(engine) as session:
        tasks = session.exec(
            select(AgentTask).where(
                AgentTask.to_agent == "product_scout",
                AgentTask.status == "pending"
            )
        ).all()
        return tasks

def mark_task_done(task_id, result):
    with Session(engine) as session:
        task = session.get(AgentTask, task_id)
        if task:
            task.status = "done"
            task.result = result
            task.completed_at = datetime.utcnow()
            session.add(task)
            session.commit()

def mark_task_failed(task_id, error):
    with Session(engine) as session:
        task = session.get(AgentTask, task_id)
        if task:
            task.status = "failed"
            task.result = error
            session.add(task)
            session.commit()

def save_memory(content, memory_type, confidence):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="product_scout",
            memory_type=memory_type,
            content=content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def create_task_for_store_manager(product_data):
    with Session(engine) as session:
        task = AgentTask(
            from_agent="product_scout",
            to_agent="store_manager",
            task_type="add_product",
            payload=json.dumps(product_data)
        )
        session.add(task)
        session.commit()

def product_already_exists(name):
    with Session(engine) as session:
        existing = session.exec(
            select(Product).where(Product.name == name)
        ).first()
        return existing is not None

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())

def scout_products(task_payload):
    vision = None
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

    vision_context = f"Monthly vision: {vision.vision}\nTarget products: {vision.target_products}" if vision else ""

    prompt = f"""You are a Product Scout Agent for BrandDrop, a premium discount sneaker and sportswear store.

{vision_context}

Market Intelligence has found the following opportunity:
- Keywords: {task_payload.get('product_keywords', '')}
- Recommended products: {task_payload.get('recommended_products', [])}
- Target demographic: {task_payload.get('target_demographic', '')}
- Demand signal: {task_payload.get('demand_signal', '')}
- Platform: {task_payload.get('platform', '')}

Based on this intelligence, generate 2-3 specific products we should add to our store.
These should be real products from brands like Nike, Adidas, New Balance, Puma, Reebok, Under Armour, etc.

Return a JSON array of products:
[
  {{
    "name": "exact product name",
    "brand": "brand name",
    "category": "Shoes/Clothing/Accessories",
    "description": "compelling product description",
    "original_price": 150.00,
    "discount_percent": 25.0,
    "final_price": 112.50,
    "stock": 50,
    "shipping_days": 5,
    "supplier_name": "suggested supplier",
    "why_this_product": "reason based on market intelligence",
    "confidence": 0.85
  }}
]

Return ONLY valid JSON array, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return parse_json_response(message.content[0].text)

def run_product_scout():
    print("[Product Scout] Checking for pending tasks...")
    tasks = get_pending_tasks()

    if not tasks:
        print("[Product Scout] No pending tasks")
        return

    for task in tasks:
        print(f"[Product Scout] Processing task {task.id}")
        try:
            payload = json.loads(task.payload)
            products = scout_products(payload)

            added = 0
            for product in products:
                if not product_already_exists(product["name"]):
                    create_task_for_store_manager(product)
                    save_memory(
                        content=f"Scouted product: {product['name']} by {product['brand']} — {product.get('why_this_product', '')}",
                        memory_type="product",
                        confidence=product.get("confidence", 0.7)
                    )
                    added += 1
                    print(f"[Product Scout] Found: {product['name']} ({product['brand']})")
                else:
                    print(f"[Product Scout] Already exists: {product['name']}")

            mark_task_done(task.id, f"Scouted {added} new products")

        except Exception as e:
            print(f"[Product Scout] Error on task {task.id}: {e}")
            mark_task_failed(task.id, str(e))