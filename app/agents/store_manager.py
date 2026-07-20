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
    Used by bulk import and other agents that already have Mikisi-formatted data.

    If the product already exists by supplier SKU and cost changed >5%,
    pricing is recalculated and the record is updated instead.
    """
    with Session(engine) as session:
        cj_pid = product_data.get("cj_product_id")
        if cj_pid:
            existing = session.exec(
                select(Product).where(Product.cj_product_id == cj_pid)
            ).first()
            if existing:
                # Cost-change resync
                new_cost = product_data.get("silverbene_cost")
                old_cost = existing.silverbene_cost
                if new_cost and old_cost and abs(new_cost - old_cost) / old_cost > 0.05:
                    from app.agents.jewelry_pricing import calculate_mikisi_price, detect_material
                    material_key = detect_material(existing.name, [])
                    pricing = calculate_mikisi_price(new_cost, material_key)
                    existing.silverbene_cost  = new_cost
                    existing.final_price      = pricing["final_price"]
                    existing.original_price   = pricing["original_price"]
                    existing.shipping_cost    = pricing["shipping_cost"]
                    existing.markup_used      = pricing["markup_used"]
                    existing.last_price_sync  = datetime.utcnow()
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                    print(f"[Store Manager] 💰 Price resynced for {existing.name}: "
                          f"${old_cost:.2f} → ${new_cost:.2f} cost, "
                          f"new price ${pricing['final_price']}")
                    return existing, "price_updated"
                return None, "already_exists"

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
            variants=product_data.get("variants"),
            material=product_data.get("material") or None,
            sizes=product_data.get("sizes") or None,
            colors=product_data.get("colors") or None,
            specs=product_data.get("specs") or None,
            silverbene_cost=product_data.get("silverbene_cost"),
            markup_used=product_data.get("markup_used"),
            shipping_cost=product_data.get("shipping_cost"),
            last_price_sync=datetime.utcnow(),
            is_premium=product_data.get("is_premium", False),
            needs_review=product_data.get("needs_review", False),
            is_active=not product_data.get("needs_review", False),
            is_published=False,   # new imports start in staging — Dennis publishes manually
        )
        session.add(product)
        session.commit()
        session.refresh(product)

        # Populate ProductVariant rows (the first-class internal variant
        # identity — see app.models.product_variant) for this new import,
        # via the same per-option parser that already produced product.sizes/
        # colors above, so the two can never disagree. Never blocks/fails the
        # import itself — a variant-row problem shouldn't prevent the product
        # from being created, the same way the Cloudinary caching below is
        # backgrounded rather than load-bearing.
        if product.variants:
            try:
                from app.models.product_variant import ProductVariant
                from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
                from app.agents.jewelry_pricing import calculate_mikisi_price
                _sb_adapter = SilverbeneAdapter()
                for row in _sb_adapter._extract_variant_rows(json.loads(product.variants), product.category or ""):
                    option_id = str(row["option_id"]) if row["option_id"] is not None else None
                    base_price = float(row["base_price"] or 0)
                    if not option_id or not base_price:
                        continue
                    session.add(ProductVariant(
                        product_id=product.id,
                        supplier_name="Silverbene",
                        supplier_option_id=option_id,
                        size=row["size"],
                        color=_sb_adapter._finalize_variant_color(row["color"], product.description or ""),
                        raw_attributes=json.dumps(row["raw_attributes"]),
                        base_price=base_price,
                        final_price=calculate_mikisi_price(base_price)["final_price"],
                        stock=int(row["qty"] or 0),
                        available=bool(row["available"]),
                        sort_order=row["sort_order"],
                    ))
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"[Store Manager] ProductVariant backfill failed for new product {product.id}: {e}")

        # Cache the primary image AND the full gallery on Cloudinary so nothing
        # about this product is ever re-fetched from Silverbene's slow, flaky
        # origin again — see image_cdn_agent.py's docstring (storefront) and
        # the 2026-07-19 Instagram posting failures (carousel posts hotlinking
        # raw Silverbene gallery URLs hit real intermittent 503s from their
        # CDN; campaign/hero posts, which already used Cloudinary via RAWSHOT,
        # had zero failures). Dennis pays for Cloudinary storage monthly —
        # every image should be cached here once, permanently, not downloaded
        # from Silverbene on every use. Backgrounded: this is the single point
        # both import pipelines (bulk_import_agent.py and product_rewriter.py's
        # path) converge on, so it must never block or fail the import itself.
        if product.image_url or product.images:
            import threading
            def _cache_images(pid=product.id, primary_url=product.image_url, gallery_json=product.images):
                from app.agents.cloudinary_agent import store_product_image
                import json as _json

                cloudinary_primary = store_product_image(pid, primary_url, "primary") if primary_url else ""

                cloudinary_gallery = []
                try:
                    gallery = _json.loads(gallery_json) if gallery_json else []
                except Exception:
                    gallery = []
                for i, url in enumerate(gallery):
                    if not url:
                        continue
                    cached = store_product_image(pid, url, f"gallery_{i}")
                    cloudinary_gallery.append(cached or url)  # keep original as fallback rather than drop the slot

                if cloudinary_primary or cloudinary_gallery:
                    with Session(engine) as s2:
                        p2 = s2.get(Product, pid)
                        if p2:
                            if cloudinary_primary:
                                p2.content_image_url = cloudinary_primary
                            if cloudinary_gallery:
                                p2.content_images = _json.dumps(cloudinary_gallery)
                            s2.add(p2)
                            s2.commit()
            threading.Thread(target=_cache_images, daemon=True).start()

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
        # PRICING — use pre-computed if provided, else fallback markup
        # ============================================================
        if standard_product.get("final_price"):
            final_price = float(standard_product["final_price"])
            original_price = float(standard_product.get(
                "original_price", round(final_price * 1.35 - 0.01, 0) + 0.99))
            discount = int(standard_product.get(
                "discount_percent", round((1 - final_price / original_price) * 100)))
        else:
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

            # Pinterest — catalog sync + pin creation (non-blocking)
            try:
                import threading
                from app.agents.pinterest_agent import sync_product as _pinterest_sync
                threading.Thread(
                    target=_pinterest_sync, args=(product,), daemon=True
                ).start()
            except Exception as e:
                print(f"[Store Manager] Pinterest sync skipped: {e}")

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