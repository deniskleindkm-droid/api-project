import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, AgentTask
from app.models.product import Product

def get_pending_tasks():
    with Session(engine) as session:
        tasks = session.exec(
            select(AgentTask).where(
                AgentTask.to_agent == "store_manager",
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
            agent_name="store_manager",
            memory_type=memory_type,
            content=content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def add_product_to_store(product_data):
    with Session(engine) as session:
        existing = session.exec(
            select(Product).where(Product.name == product_data["name"])
        ).first()
        
        if existing:
            return None, "already_exists"
        
        product = Product(
            name=product_data["name"],
            brand=product_data["brand"],
            category=product_data.get("category", "Shoes"),
            description=product_data["description"],
            original_price=float(product_data["original_price"]),
            discount_percent=float(product_data["discount_percent"]),
            final_price=float(product_data["final_price"]),
            stock=int(product_data.get("stock", 50)),
            shipping_days=int(product_data.get("shipping_days", 7)),
            supplier_name=product_data.get("supplier_name"),
            is_active=True
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return product, "added"

def create_task_for_marketing(product_data, product_id):
    with Session(engine) as session:
        task = AgentTask(
            from_agent="store_manager",
            to_agent="marketing",
            task_type="market",
            payload=json.dumps({**product_data, "product_id": product_id})
        )
        session.add(task)
        session.commit()

def run_store_manager():
    print("[Store Manager] Checking for pending tasks...")
    tasks = get_pending_tasks()
    
    if not tasks:
        print("[Store Manager] No pending tasks")
        return
    
    for task in tasks:
        print(f"[Store Manager] Processing task {task.id}")
        try:
            product_data = json.loads(task.payload)
            product, status = add_product_to_store(product_data)
            
            if status == "added" and product:
                print(f"[Store Manager] ✅ Added to store: {product.name}")
                save_memory(
                    content=f"Added product: {product.name} by {product.brand} at ${product.final_price}",
                    memory_type="product",
                    confidence=0.9
                )
                create_task_for_marketing(product_data, product.id)
                mark_task_done(task.id, f"Added product ID {product.id}: {product.name}")
            else:
                print(f"[Store Manager] Product already exists: {product_data['name']}")
                mark_task_done(task.id, "Product already exists")
                
        except Exception as e:
            print(f"[Store Manager] Error on task {task.id}: {e}")
            mark_task_failed(task.id, str(e))