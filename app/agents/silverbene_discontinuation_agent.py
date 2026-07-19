"""
Silverbene Discontinuation Agent

Runs automatically after every stock sync cycle.

Existence at Silverbene is now decided directly and immediately by the stock
sync itself (silverbene_stock_agent.py Step 4b) — a clean SKU lookup every
cycle, not a miss streak. The moment that lookup comes back with a confirmed
"doesn't exist" response, the product is unpublished right away and
Product.confirmed_gone_at is stamped.

This agent's job, every cycle:

  1. Sweep: permanently delete any product whose confirmed_gone_at is 7+ days
     old and still hasn't been found again — Silverbene gets a real week to
     restock/relist before anything is removed for good.
  2. Report: one batched email covering what's newly gone, what's still
     inside its grace period (with days remaining), and what got deleted.

Recovery (a previously-gone product found again) is called directly by the
stock sync via handle_recovery() below the moment its existence check finds
the SKU again — this cancels the countdown immediately, it doesn't wait for
this agent's next run.

sync_miss_count is purely diagnostic now — it only means "the existence
check's own API call failed N times in a row" (network/timeout/etc). It is
never evidence a product is gone and never triggers deletion or unpublish.
"""

import json
from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product


GRACE_PERIOD_DAYS = 7


# ─── Public entry points ──────────────────────────────────────────────────────

def run_discontinuation_agent():
    """
    Main entry point — called at end of each stock sync run.
    Deletes anything past its 7-day grace period, then sends one batched
    report covering newly-gone / still-in-grace / deleted this cycle.
    """
    print(f"\n[Discontinuation Agent] Starting — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    with Session(engine) as session:
        gone = session.exec(
            select(Product).where(
                Product.supplier_name == "Silverbene",
                Product.confirmed_gone_at.is_not(None),
            )
        ).all()

    if not gone:
        print("[Discontinuation Agent] No products currently marked gone at Silverbene")
        return {"checked": 0, "deleted": 0, "in_grace_period": 0}

    print(f"[Discontinuation Agent] {len(gone)} product(s) confirmed gone at Silverbene, checking grace periods")

    deleted = []      # (name, category, sku)
    in_grace = []     # (name, category, sku, days_remaining)

    for product in gone:
        days_gone = (datetime.utcnow() - product.confirmed_gone_at).total_seconds() / 86400
        entry = (product.name, product.category or "Uncategorised", product.cj_product_id or "N/A")

        if days_gone >= GRACE_PERIOD_DAYS:
            print(f"[Discontinuation Agent] Deleting permanently (gone {days_gone:.1f} days, "
                  f"grace period expired): [{product.id}] {product.name[:55]}")
            try:
                from app.agents.cloudinary_agent import delete_product_assets
                delete_product_assets(product.id)
            except Exception as e:
                print(f"[Discontinuation Agent] Cloudinary cleanup error for {product.id}: {e}")
            with Session(engine) as session:
                p = session.get(Product, product.id)
                if p:
                    session.delete(p)
                    session.commit()
            deleted.append(entry)
        else:
            in_grace.append((*entry, round(GRACE_PERIOD_DAYS - days_gone, 1)))

    if in_grace or deleted:
        _send_batched_report(in_grace, deleted)

    result = {
        "checked": len(gone),
        "deleted": len(deleted),
        "in_grace_period": len(in_grace),
    }
    _write_memory(result, [n for n, _, _ in deleted], [n for n, _, _, _ in in_grace])
    print(f"[Discontinuation Agent] Done — deleted={len(deleted)} in_grace_period={len(in_grace)}")
    return result


def handle_recovery(product_id: int, fresh_data: dict):
    """
    Called by the stock sync the moment a previously-gone product's existence
    check finds it again at Silverbene. Cancels the deletion countdown,
    refreshes core fields, and lands the product in Unpublished for manual
    review — never auto-goes-live.
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return

        was_gone_since = product.confirmed_gone_at
        product.confirmed_gone_at = None
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

        gone_for = f"{(datetime.utcnow() - was_gone_since).total_seconds() / 86400:.1f} days" if was_gone_since else "unknown"
        print(f"[Discontinuation Agent] Recovery: {product.name[:50]} (was gone {gone_for}) → Unpublished")

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
                        "sku": product.cj_product_id,
                        "was_gone_since": was_gone_since.isoformat() if was_gone_since else None,
                    }),
                    confidence=1.0,
                ))
                mem_session.commit()
        except Exception as e:
            print(f"[Discontinuation Agent] Recovery memory write error: {e}")

        _send_email(
            subject=f"Mikisi — Product Recovered: {product.name[:50]}",
            lines=[
                f"Good news — <strong>{product.name}</strong> is back at Silverbene "
                f"(was gone {gone_for}, before its 7-day removal window ran out).",
                "",
                f"It has been moved to <strong>Unpublished</strong> in the Catalog Manager.",
                "Review it and publish when you're ready to list it again.",
                "",
                f"Category: {product.category} &nbsp;|&nbsp; SKU: {product.cj_product_id}",
            ],
            urgency="low",
        )


# ─── Internal handlers ────────────────────────────────────────────────────────

def _send_batched_report(in_grace: list, deleted: list):
    """
    One email covering all gone/grace-period/deleted products this cycle,
    grouped by collection. in_grace items carry days_remaining as their 4th field.
    """
    def _group_by_category(items):
        groups = {}
        for entry in items:
            name, cat = entry[0], entry[1]
            groups.setdefault(cat, []).append(entry)
        return groups

    sections = []

    if in_grace:
        groups = _group_by_category(in_grace)
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{cat}</td>"
            f"<td style='padding:4px 0'>"
            + "".join(
                f"{name} <span style='color:#aaa;font-size:11px'>({sku}, {days_left}d left)</span><br>"
                for name, _, sku, days_left in prods
            )
            + "</td></tr>"
            for cat, prods in sorted(groups.items())
        )
        sections.append(
            f"<h3 style='color:#dc2626;margin:20px 0 6px'>⚠ Confirmed gone at Silverbene ({len(in_grace)})</h3>"
            f"<p style='color:#555;margin:0 0 8px;font-size:13px'>Already unpublished. "
            f"Will be permanently deleted if Silverbene hasn't relisted them by the deadline shown.</p>"
            f"<table style='border-collapse:collapse;font-size:13px'>{rows}</table>"
        )

    if deleted:
        groups = _group_by_category(deleted)
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{cat}</td>"
            f"<td style='padding:4px 0'>"
            + "".join(f"{name} <span style='color:#aaa;font-size:11px'>({sku})</span><br>" for name, _, sku in prods)
            + "</td></tr>"
            for cat, prods in sorted(groups.items())
        )
        sections.append(
            f"<h3 style='color:#7c3aed;margin:20px 0 6px'>✗ Permanently deleted ({len(deleted)})</h3>"
            f"<p style='color:#555;margin:0 0 8px;font-size:13px'>Gone at Silverbene for {GRACE_PERIOD_DAYS}+ days "
            f"with no relisting. Removed from database.</p>"
            f"<table style='border-collapse:collapse;font-size:13px'>{rows}</table>"
        )

    total = len(in_grace) + len(deleted)
    subject = f"Mikisi — {total} Product{'s' if total != 1 else ''} Gone/Removed at Silverbene"
    body = (
        "<div style='font-family:sans-serif;max-width:620px;margin:0 auto;padding:24px'>"
        "<p style='color:#333'>Silverbene existence check flagged the following this cycle:</p>"
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


def _write_memory(result: dict, deleted: list, in_grace: list):
    try:
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="silverbene_discontinuation_agent",
                memory_type="check_run",
                content=json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    **result,
                    "deleted_names": deleted[:10],
                    "in_grace_names": in_grace[:10],
                }),
                confidence=1.0,
            ))
            session.commit()
    except Exception as e:
        print(f"[Discontinuation Agent] Memory write error: {e}")
