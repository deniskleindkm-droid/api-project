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
    """
    Save a product to the store from internal product_data dict.
    Used by CJ and other agents that already have Mikisi-formatted data.
    """
    with Session(engine) as session:
        existing = session.exec(
            select(Product).where(
                Product.name == product_data["name"],
                Product.is_active == True
            )
        ).first()

        if existing:
            return None, "already_exists"

        product = Product(
            name=product_data["name"],
            brand=product_data["brand"],
            category=product_data.get("category", "Beauty"),
            description=product_data["description"],
            original_price=float(product_data["original_price"]),
            discount_percent=float(product_data["discount_percent"]),
            final_price=float(product_data["final_price"]),
            image_url=product_data.get("image_url", ""),
            images=product_data.get("images"),
            stock=int(product_data.get("stock", 50)),
            shipping_days=int(product_data.get("shipping_days", 7)),
            supplier_name=product_data.get("supplier_name"),
            supplier_url=product_data.get("supplier_url"),
            collection_id=product_data.get("collection_id"),
            cj_product_id=product_data.get("cj_product_id"),
            cj_sku=product_data.get("cj_sku"),
            is_active=True
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return product, "added"


def import_product_from_supplier(standard_product: dict, markup: float = None) -> dict:
    """
    Universal importer — accepts standard supplier format.
    Every product goes through ARIA rewriter before saving.
    ARIA assigns correct collection, rewrites name and description.
    Rejects anything that doesn't fit Mikisi's 6 collections.
    """
    if markup is None:
        from app.agents.store_config import get_config
        markup = get_config("default_markup", default=7.0)

    try:
        name = standard_product.get("name", "")
        cost_price = float(standard_product.get("cost_price", 0))
        category = standard_product.get("category", "Beauty")
        supplier_name = standard_product.get("supplier_name", "")
        variants = standard_product.get("variants", [])
        description = standard_product.get("description", name)

        # ============================================================
        # ARIA REWRITER — every product goes through this
        # ============================================================
        try:
            from app.agents.product_rewriter import rewrite_product
            rewrite_result = rewrite_product({
                "name": name,
                "category": category,
                "description": description,
                "final_price": cost_price * markup
            })

            if not rewrite_result.get("accepted"):
                reason = rewrite_result.get("rejection_reason", "Does not fit Mikisi collections")
                print(f"[Store Manager] ❌ Rejected: {name[:50]} — {reason}")
                return {"success": False, "reason": reason, "rejected": True}

            # Use Mikisi identity
            mikisi_name = rewrite_result.get("mikisi_name", name)[:100]
            mikisi_description = rewrite_result.get("mikisi_description", description)
            collection_id = rewrite_result.get("collection_id")
            print(f"[Store Manager] ✍️ Rewritten: '{name[:40]}' → '{mikisi_name}'")

        except Exception as e:
            print(f"[Store Manager] Rewriter failed — using raw data: {e}")
            mikisi_name = name[:100]
            mikisi_description = description
            collection_id = None

        # ============================================================
        # PRICING
        # ============================================================
        marked_up = cost_price * markup
        final_price = int(marked_up) + 0.99
        original_price = int(final_price * 1.4) + 0.99
        discount = round((1 - final_price / original_price) * 100)

        # ============================================================
        # SKU
        # ============================================================
        cj_sku = ""
        if variants:
            cj_sku = variants[0].get("variantSku", "") or variants[0].get("vid", "")

        # ============================================================
        # SAVE TO DATABASE
        # ============================================================
        product_data = {
            "name": mikisi_name,
            "brand": "Mikisi",
            "category": category,
            "description": mikisi_description,
            "original_price": original_price,
            "discount_percent": discount,
            "final_price": final_price,
            "image_url": standard_product.get("image_url", ""),
            "images": standard_product.get("images"),
            "stock": int(standard_product.get("stock", 999)),
            "shipping_days": int(standard_product.get("shipping_days", 15)),
            "supplier_name": supplier_name,
            "supplier_url": standard_product.get("supplier_url", ""),
            "cj_product_id": standard_product.get("supplier_product_id", ""),
            "cj_sku": cj_sku,
            "collection_id": collection_id,
        }

        product, status = add_product_to_store(product_data)

        if status == "added" and product:
            try:
                from app.agents.nervous_system import emit
                emit(
                    signal_type="PRODUCT_IMPORTED",
                    sender="store_manager",
                    payload={
                        "product_id": product.id,
                        "name": mikisi_name,
                        "collection_id": collection_id,
                        "store_price": final_price,
                        "cost_price": cost_price,
                        "supplier": supplier_name
                    },
                    priority=5
                )
            except Exception as e:
                print(f"[Store Manager] Signal emission failed: {e}")

            print(f"[Store Manager] ✅ Imported: {mikisi_name} at ${final_price}")
            return {
                "success": True,
                "product": mikisi_name,
                "product_id": product.id,
                "cost_price": cost_price,
                "store_price": final_price,
                "markup_applied": markup,
                "collection_id": collection_id,
                "supplier": supplier_name
            }

        return {"success": False, "reason": "Already exists"}

    except Exception as e:
        print(f"[Store Manager] Universal import error: {e}")
        return {"success": False, "reason": str(e)}


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