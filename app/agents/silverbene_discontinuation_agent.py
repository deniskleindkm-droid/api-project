"""
Silverbene Discontinuation Agent

Runs automatically after every stock sync cycle.

Each product the stock sync cannot find on Silverbene gets a miss recorded.
This agent acts on those misses:

  Miss 1  → product already unpublished by stock sync
             → email Dennis immediately: "Product X missing at Silverbene"
             → product appears in Discontinued folder in admin

  Miss 2  → email Dennis again: still not found after second check

  Miss 3  → make one final direct API call to confirm
             → if still not found: DELETE from database permanently + email Dennis
             → if found (false alarm): treat as recovery

Recovery (stock sync finds a previously-missed product):
  → called by stock sync with fresh Silverbene data
  → update all product fields from Silverbene
  → reset sync_miss_count = 0
  → move to Unpublished for Dennis to review before going live
  → email Dennis: "Product X found again — review and publish when ready"
"""

import os
import json
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product


MISS_THRESHOLD = 3  # delete after this many consecutive misses


# ─── Public entry points ──────────────────────────────────────────────────────

def run_discontinuation_agent():
    """
    Main entry point — called at end of each stock sync run.
    Acts on all products with sync_miss_count >= 1.
    """
    print(f"\n[Discontinuation Agent] Starting — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    with Session(engine) as session:
        missed = session.exec(
            select(Product).where(
                Product.supplier_name == "Silverbene",
                Product.sync_miss_count >= 1,
            )
        ).all()

    if not missed:
        print("[Discontinuation Agent] No missing products — all SKUs found in last sync")
        return {"checked": 0, "notified": 0, "deleted": 0, "recovered": 0}

    print(f"[Discontinuation Agent] {len(missed)} products with consecutive misses")

    notified = []
    deleted = []

    for product in missed:
        count = product.sync_miss_count

        if count >= MISS_THRESHOLD:
            _handle_final_miss(product)
            deleted.append(product.name)

        elif count == 2:
            _notify_second_miss(product)
            notified.append(product.name)

        elif count == 1:
            _notify_first_miss(product)
            notified.append(product.name)

    result = {
        "checked":   len(missed),
        "notified":  len(notified),
        "deleted":   len(deleted),
    }

    _write_memory(result, notified, deleted)
    print(f"[Discontinuation Agent] Done — notified={len(notified)} deleted={len(deleted)}")
    return result


def handle_recovery(product_id: int, fresh_data: dict):
    """
    Called by the stock sync when a previously-missed product is found again.
    Updates product data and moves it back to Unpublished.
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return

        old_miss_count = product.sync_miss_count
        product.sync_miss_count = 0
        product.is_published = False          # lands in Unpublished for review
        product.stock_auto_unpublished = False

        # Update core fields from fresh Silverbene data
        if fresh_data.get("stock") is not None:
            product.stock = fresh_data["stock"]
        if fresh_data.get("final_price"):
            product.final_price = fresh_data["final_price"]
        if fresh_data.get("original_price"):
            product.original_price = fresh_data["original_price"]
        if fresh_data.get("image_url"):
            product.image_url = fresh_data["image_url"]
        if fresh_data.get("sizes"):
            product.sizes = json.dumps(fresh_data["sizes"]) if isinstance(fresh_data["sizes"], list) else fresh_data["sizes"]
        if fresh_data.get("colors"):
            product.colors = json.dumps(fresh_data["colors"]) if isinstance(fresh_data["colors"], list) else fresh_data["colors"]

        session.add(product)
        session.commit()

        print(f"[Discontinuation Agent] Recovery: {product.name[:50]} (was {old_miss_count} misses) → Unpublished")

        _send_email(
            subject=f"Mikisi — Product Recovered: {product.name[:50]}",
            lines=[
                f"Good news — <strong>{product.name}</strong> has been found again on Silverbene "
                f"after {old_miss_count} consecutive sync miss(es).",
                "",
                f"It has been moved to <strong>Unpublished</strong> in the Catalog Manager.",
                "Review it and publish when you're ready to list it again.",
                "",
                f"Category: {product.category} &nbsp;|&nbsp; SKU: {product.cj_sku}",
            ],
            urgency="low",
        )


# ─── Internal handlers ────────────────────────────────────────────────────────

def _handle_final_miss(product: Product):
    """3rd miss — make one last API call to confirm, then delete if still gone."""
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    sb = SilverbeneAdapter()

    sku = product.cj_sku
    confirmed_gone = True

    if sku:
        resp = sb._get("/api/dropshipping/option_qty", {"option_id": sku})
        if isinstance(resp, dict) and resp.get("code") == 0:
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                # Silverbene found it — false alarm, treat as recovery
                item = data[0] if data else {}
                qty = int(item.get("qty", item.get("qyt", 0)) or 0)
                handle_recovery(product.id, {"stock": qty})
                confirmed_gone = False

    if confirmed_gone:
        print(f"[Discontinuation Agent] DELETING permanently: [{product.id}] {product.name[:55]}")
        _send_email(
            subject=f"Mikisi — Product Permanently Removed: {product.name[:50]}",
            lines=[
                f"<strong>{product.name}</strong> could not be found on Silverbene "
                f"after {MISS_THRESHOLD} consecutive sync checks (every 6 hours).",
                "",
                "The product has been <strong>permanently deleted</strong> from the Mikisi database.",
                "Silverbene has discontinued this item — it will not return.",
                "",
                f"Category: {product.category} &nbsp;|&nbsp; SKU: {sku or 'N/A'}",
                "",
                "No action needed. The store has already been updated.",
            ],
            urgency="high",
        )
        with Session(engine) as session:
            p = session.get(Product, product.id)
            if p:
                session.delete(p)
                session.commit()


def _notify_first_miss(product: Product):
    print(f"[Discontinuation Agent] Miss 1 — notifying Dennis: {product.name[:55]}")
    _send_email(
        subject=f"Mikisi — Product Not Found at Silverbene: {product.name[:50]}",
        lines=[
            f"<strong>{product.name}</strong> could not be found at Silverbene during the last stock sync.",
            "",
            "The product has been <strong>hidden from the storefront</strong> immediately.",
            "It now appears in the <strong>Discontinued</strong> folder in your Catalog Manager.",
            "",
            "This may be temporary (Silverbene API hiccup) or the product may have been discontinued.",
            f"The system will check again in the next sync cycle (6 hours).",
            "",
            f"Category: {product.category} &nbsp;|&nbsp; SKU: {product.cj_sku or 'N/A'}",
            "",
            "If it is found again, it will be moved to Unpublished for your review.",
            f"If it is not found after {MISS_THRESHOLD} checks, it will be permanently deleted.",
        ],
        urgency="medium",
    )


def _notify_second_miss(product: Product):
    print(f"[Discontinuation Agent] Miss 2 — still missing: {product.name[:55]}")
    _send_email(
        subject=f"Mikisi — Still Missing at Silverbene (Check 2/3): {product.name[:50]}",
        lines=[
            f"<strong>{product.name}</strong> was not found at Silverbene again in this sync cycle.",
            "",
            f"This is the <strong>2nd consecutive miss</strong>. One more check remaining.",
            "The product remains hidden from the storefront.",
            "",
            f"If it is not found in the next sync (in ~6 hours), it will be "
            f"<strong>permanently deleted</strong> from the database.",
            "",
            f"Category: {product.category} &nbsp;|&nbsp; SKU: {product.cj_sku or 'N/A'}",
        ],
        urgency="medium",
    )


def _send_email(subject: str, lines: list, urgency: str = "medium"):
    try:
        from app.agents.email_partner import send_email
        dennis_email = os.getenv("DENNIS_EMAIL")
        if not dennis_email:
            return
        body = "<br>".join(lines)
        send_email(dennis_email, subject, body, is_html=True)
    except Exception as e:
        print(f"[Discontinuation Agent] Email error: {e}")


def _write_memory(result: dict, notified: list, deleted: list):
    try:
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="silverbene_discontinuation_agent",
                memory_type="check_run",
                content=json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    **result,
                    "notified_names": notified[:10],
                    "deleted_names":  deleted[:10],
                }),
                confidence=1.0,
            ))
            session.commit()
    except Exception as e:
        print(f"[Discontinuation Agent] Memory write error: {e}")
