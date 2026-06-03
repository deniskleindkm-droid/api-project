from dotenv import load_dotenv
load_dotenv()

import os
import json
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product


def run_silverbene_stock_agent():
    """
    Silverbene Stock Agent — runs every 6 hours automatically.

    What it does:
    1. Fetches live stock for every Silverbene product via option_qty API
    2. Updates stock quantity in the store
    3. Deactivates products that are out of stock at Silverbene
    4. Reactivates products when stock returns
    5. ARIA reviews the changes and emails Dennis if action is needed
    """

    print(f"\n[Silverbene Stock Agent] 🔄 Starting stock sync — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        sb = SilverbeneAdapter()

        # ── Step 1: Load all active Silverbene products ───────────────────────
        with Session(engine) as session:
            active_products = session.exec(
                select(Product).where(Product.supplier_name == "Silverbene", Product.is_active == True)
            ).all()
            # Also check recently deactivated ones — they may be back in stock
            inactive_products = session.exec(
                select(Product).where(Product.supplier_name == "Silverbene", Product.is_active == False)
            ).all()

        all_products = list(active_products) + list(inactive_products)

        if not all_products:
            print("[Silverbene Stock Agent] No Silverbene products in store")
            return {"checked": 0, "updated": 0, "deactivated": 0, "reactivated": 0}

        # ── Step 2: Build option_id → product map ────────────────────────────
        id_map = {}
        for p in all_products:
            if p.cj_sku:
                id_map[str(p.cj_sku)] = p.id

        if not id_map:
            print("[Silverbene Stock Agent] No option_ids found on products — cannot check stock")
            return {"checked": 0, "updated": 0, "deactivated": 0, "reactivated": 0}

        print(f"[Silverbene Stock Agent] Checking {len(id_map)} products against Silverbene live inventory")

        # ── Step 3: Check stock in batches of 50 ────────────────────────────
        updated = 0
        deactivated = 0
        reactivated = 0
        newly_outofstock = []
        newly_reactivated = []

        option_ids = list(id_map.keys())
        batch_size = 50

        for i in range(0, len(option_ids), batch_size):
            batch = option_ids[i:i + batch_size]
            resp = sb._get("/api/dropshipping/option_qty", {
                "option_id": ",".join(batch)
            })

            if not isinstance(resp, dict) or resp.get("code") != 0:
                print(f"[Silverbene Stock Agent] API error: {resp.get('message') if isinstance(resp, dict) else resp}")
                continue

            stock_data = resp.get("data", [])
            if not isinstance(stock_data, list):
                continue

            with Session(engine) as session:
                for item in stock_data:
                    if not isinstance(item, dict):
                        continue
                    option_id = str(item.get("option_id", ""))
                    qty = int(item.get("qty", 0) or 0)
                    product_id = id_map.get(option_id)
                    if not product_id:
                        continue

                    product = session.get(Product, product_id)
                    if not product:
                        continue

                    if qty == 0:
                        if product.is_active:
                            product.is_active = False
                            product.stock = 0
                            session.add(product)
                            deactivated += 1
                            newly_outofstock.append(product.name[:60])
                            print(f"[Silverbene Stock Agent] ⚠ Out of stock → hidden: {product.name[:50]}")
                    else:
                        stock_changed = product.stock != qty
                        was_inactive = not product.is_active

                        product.stock = qty
                        product.is_active = True
                        session.add(product)

                        if was_inactive:
                            reactivated += 1
                            newly_reactivated.append(product.name[:60])
                            print(f"[Silverbene Stock Agent] ✅ Back in stock → visible: {product.name[:50]}")
                        elif stock_changed:
                            updated += 1

                session.commit()

        total_checked = len(id_map)
        print(f"\n[Silverbene Stock Agent] ✅ Sync complete:")
        print(f"  • Checked: {total_checked} products")
        print(f"  • Stock updated: {updated}")
        print(f"  • Deactivated (out of stock): {deactivated}")
        print(f"  • Reactivated (back in stock): {reactivated}")

        # ── Step 4: ARIA reviews changes and alerts Dennis if needed ─────────
        if deactivated > 0 or reactivated > 0:
            _aria_stock_report(
                total_checked=total_checked,
                updated=updated,
                deactivated=deactivated,
                reactivated=reactivated,
                newly_outofstock=newly_outofstock,
                newly_reactivated=newly_reactivated
            )

        return {
            "checked": total_checked,
            "updated": updated,
            "deactivated": deactivated,
            "reactivated": reactivated,
            "newly_outofstock": newly_outofstock,
            "newly_reactivated": newly_reactivated,
        }

    except Exception as e:
        import traceback
        print(f"[Silverbene Stock Agent] Error: {e}")
        traceback.print_exc()
        return {"error": str(e)}


def _aria_stock_report(total_checked, updated, deactivated, reactivated,
                       newly_outofstock, newly_reactivated):
    """ARIA thinks about the stock changes and emails Dennis if action is needed."""
    try:
        from app.agents.aria_intelligence import aria_think
        from app.agents.aria_memory import store_episode
        from app.agents.email_partner import send_email

        outofstock_list = "\n".join(f"- {name}" for name in newly_outofstock[:10])
        reactivated_list = "\n".join(f"- {name}" for name in newly_reactivated[:10])

        situation = (
            f"Silverbene stock sync completed. "
            f"Checked {total_checked} products. "
            f"{deactivated} products went out of stock at Silverbene and have been hidden from the store. "
            f"{reactivated} products came back in stock and are now visible again. "
            f"{updated} products had their stock quantity updated. "
            + (f"\nOut of stock: {outofstock_list}" if newly_outofstock else "")
            + (f"\nBack in stock: {reactivated_list}" if newly_reactivated else "")
            + "\nDennis should know if action is needed — e.g. replacing out-of-stock products or celebrating restocks."
        )

        result = aria_think(situation=situation, urgency="medium" if deactivated > 2 else "low")

        store_episode(
            event=f"Stock sync: {deactivated} out of stock, {reactivated} reactivated",
            context=situation[:200],
            decision="ARIA reviewed stock changes and notified Dennis",
            outcome="stock_synced",
            significance="medium" if deactivated > 0 else "low"
        )

        dennis_email = os.getenv("DENNIS_EMAIL")
        if dennis_email and result:
            urgency = result.get("urgency_level", "low")
            if urgency in ["high", "medium"] or deactivated > 0 or reactivated > 0:
                email_data = result.get("email_to_dennis", {})
                subject = email_data.get("subject", f"Mikisi Stock Update — {deactivated} out of stock, {reactivated} restocked")
                body = email_data.get("body", "")
                if body:
                    send_email(dennis_email, subject, body, is_html=True)
                    print(f"[Silverbene Stock Agent] ✉ ARIA stock report sent to Dennis")

    except Exception as e:
        print(f"[Silverbene Stock Agent] ARIA report error: {e}")
