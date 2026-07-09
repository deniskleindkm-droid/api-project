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
    Sends ONE batched report email grouped by collection, not one per product.
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

    # Collect all actions — no emails fired inside the loop
    first_miss  = []   # (name, category, sku)
    second_miss = []
    deleted     = []

    for product in missed:
        count = product.sync_miss_count
        entry = (product.name, product.category or "Uncategorised", product.cj_sku or "N/A")

        if count >= MISS_THRESHOLD:
            _handle_final_miss_silent(product)
            deleted.append(entry)

        elif count == 2:
            second_miss.append(entry)

        elif count == 1:
            first_miss.append(entry)

    # Send one batched report covering everything
    if first_miss or second_miss or deleted:
        _send_batched_report(first_miss, second_miss, deleted)

    notified_count = len(first_miss) + len(second_miss)
    deleted_count  = len(deleted)

    result = {
        "checked":  len(missed),
        "notified": notified_count,
        "deleted":  deleted_count,
    }

    _write_memory(result, [n for n,_,_ in first_miss+second_miss], [n for n,_,_ in deleted])
    print(f"[Discontinuation Agent] Done — notified={notified_count} deleted={deleted_count}")
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

        try:
            from app.models.agent import AgentMemory
            with Session(engine) as mem_session:
                mem_session.add(AgentMemory(
                    agent_name="silverbene_discontinuation_agent",
                    memory_type="recovery",
                    content=json.dumps({
                        "timestamp": datetime.utcnow().isoformat(),
                        "product_id": product.id,
                        "name": product.name,
                        "category": product.category,
                        "sku": product.cj_sku,
                        "was_missed": old_miss_count,
                    }),
                    confidence=1.0,
                ))
                mem_session.commit()
        except Exception as e:
            print(f"[Discontinuation Agent] Recovery memory write error: {e}")

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

def _handle_final_miss_silent(product: Product):
    """3rd miss — confirm with API, delete if still gone. No email here; batched report handles it."""
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    sb = SilverbeneAdapter()
    sku = product.cj_sku
    confirmed_gone = True

    if sku:
        resp = sb._get("/api/dropshipping/option_qty", {"option_id": sku})
        if isinstance(resp, dict) and resp.get("code") == 0:
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                qty = int((data[0] or {}).get("qty", (data[0] or {}).get("qyt", 0)) or 0)
                handle_recovery(product.id, {"stock": qty})
                confirmed_gone = False

    if confirmed_gone:
        print(f"[Discontinuation Agent] DELETING permanently: [{product.id}] {product.name[:55]}")
        with Session(engine) as session:
            p = session.get(Product, product.id)
            if p:
                session.delete(p)
                session.commit()


def _send_batched_report(first_miss: list, second_miss: list, deleted: list):
    """
    One email covering all missed products this cycle, grouped by collection.
    first_miss / second_miss / deleted are lists of (name, category, sku).
    """
    def _group_by_category(items):
        groups = {}
        for name, cat, sku in items:
            groups.setdefault(cat, []).append((name, sku))
        return groups

    sections = []

    if first_miss:
        groups = _group_by_category(first_miss)
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{cat}</td>"
            f"<td style='padding:4px 0'>"
            + "".join(f"{name} <span style='color:#aaa;font-size:11px'>({sku})</span><br>" for name, sku in prods)
            + "</td></tr>"
            for cat, prods in sorted(groups.items())
        )
        sections.append(
            f"<h3 style='color:#b45309;margin:20px 0 6px'>⚠ New — Hidden from storefront ({len(first_miss)})</h3>"
            f"<p style='color:#555;margin:0 0 8px;font-size:13px'>Not found in this sync. Will be checked again in 6 hours.</p>"
            f"<table style='border-collapse:collapse;font-size:13px'>{rows}</table>"
        )

    if second_miss:
        groups = _group_by_category(second_miss)
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{cat}</td>"
            f"<td style='padding:4px 0'>"
            + "".join(f"{name} <span style='color:#aaa;font-size:11px'>({sku})</span><br>" for name, sku in prods)
            + "</td></tr>"
            for cat, prods in sorted(groups.items())
        )
        sections.append(
            f"<h3 style='color:#dc2626;margin:20px 0 6px'>⚠ Still missing — 2nd check ({len(second_miss)})</h3>"
            f"<p style='color:#555;margin:0 0 8px;font-size:13px'>One more miss and these will be permanently deleted.</p>"
            f"<table style='border-collapse:collapse;font-size:13px'>{rows}</table>"
        )

    if deleted:
        groups = _group_by_category(deleted)
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{cat}</td>"
            f"<td style='padding:4px 0'>"
            + "".join(f"{name} <span style='color:#aaa;font-size:11px'>({sku})</span><br>" for name, sku in prods)
            + "</td></tr>"
            for cat, prods in sorted(groups.items())
        )
        sections.append(
            f"<h3 style='color:#7c3aed;margin:20px 0 6px'>✗ Permanently deleted ({len(deleted)})</h3>"
            f"<p style='color:#555;margin:0 0 8px;font-size:13px'>Confirmed gone after {MISS_THRESHOLD} checks. Removed from database.</p>"
            f"<table style='border-collapse:collapse;font-size:13px'>{rows}</table>"
        )

    total = len(first_miss) + len(second_miss) + len(deleted)
    subject = f"Mikisi — {total} Product{'s' if total!=1 else ''} Missing at Silverbene"
    body = (
        "<div style='font-family:sans-serif;max-width:620px;margin:0 auto;padding:24px'>"
        "<p style='color:#333'>Silverbene sync flagged the following products this cycle:</p>"
        + "".join(sections)
        + "<p style='color:#aaa;font-size:11px;margin-top:24px'>Mikisi autonomous stock system</p>"
        "</div>"
    )
    _send_email(subject=subject, lines=[], body=body)


def _send_email(subject: str, lines: list, urgency: str = "medium", body: str = ""):
    # Disabled — sync/recovery emails were firing on every miss-count flap,
    # flooding Dennis's inbox. Results still land in AgentMemory (see
    # _write_memory / handle_recovery) for the admin sync report instead.
    print(f"[Discontinuation Agent] Email suppressed: {subject}")
    return


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
