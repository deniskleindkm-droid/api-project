from dotenv import load_dotenv
load_dotenv()

import os
import json
import re
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product


def run_silverbene_stock_agent():
    """
    Silverbene Stock Agent — runs every 6 hours automatically.

    Every cycle:
    1. Checks live stock for every Silverbene product
    2. Updates stock quantities, marks out-of-stock, reactivates restocks
    3. Refreshes sizes for ALL categories (rings, necklaces, bracelets, anklets, etc.)
       wherever Silverbene has new or missing data
    4. Emails Dennis via ARIA whenever anything changes
    """

    print(f"\n[Silverbene Stock Agent] Starting sync — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        sb = SilverbeneAdapter()

        # ── Step 1: Load all Silverbene products (active + recently inactive) ──
        with Session(engine) as session:
            active_products = session.exec(
                select(Product).where(Product.supplier_name == "Silverbene", Product.is_active == True)
            ).all()
            inactive_products = session.exec(
                select(Product).where(Product.supplier_name == "Silverbene", Product.is_active == False)
            ).all()

        all_products = list(active_products) + list(inactive_products)

        if not all_products:
            print("[Silverbene Stock Agent] No Silverbene products in store")
            return {"checked": 0, "updated": 0, "deactivated": 0, "reactivated": 0, "sizes_updated": 0}

        # ── Step 2: Build option_id → product map ────────────────────────────
        id_map = {}
        for p in all_products:
            if p.cj_sku:
                id_map[str(p.cj_sku)] = p.id

        if not id_map:
            print("[Silverbene Stock Agent] No option_ids found — cannot check stock")
            return {"checked": 0, "updated": 0, "deactivated": 0, "reactivated": 0, "sizes_updated": 0}

        print(f"[Silverbene Stock Agent] Checking {len(id_map)} products")

        # ── Step 3: Stock check in batches of 50 ─────────────────────────────
        updated = 0
        deactivated = 0
        reactivated = 0
        newly_outofstock = []
        newly_reactivated = []
        stock_quantity_changes = []

        for i in range(0, len(list(id_map.keys())), 50):
            batch = list(id_map.keys())[i:i + 50]
            resp = sb._get("/api/dropshipping/option_qty", {"option_id": ",".join(batch)})

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
                        if product.stock != 0:
                            product.stock = 0
                            product.is_active = True
                            session.add(product)
                            deactivated += 1
                            newly_outofstock.append(product.name[:60])
                            print(f"[Silverbene Stock Agent] Out of stock: {product.name[:50]}")
                            if product.pinterest_pin_id:
                                try:
                                    from app.agents.pinterest_agent import update_product_availability
                                    update_product_availability(product.id, False)
                                except Exception:
                                    pass
                    else:
                        old_qty = product.stock
                        was_inactive = not product.is_active
                        product.stock = qty
                        product.is_active = True
                        session.add(product)

                        if was_inactive:
                            reactivated += 1
                            newly_reactivated.append(product.name[:60])
                            print(f"[Silverbene Stock Agent] Back in stock: {product.name[:50]}")
                            if product.pinterest_pin_id:
                                try:
                                    from app.agents.pinterest_agent import update_product_availability
                                    update_product_availability(product.id, True)
                                except Exception:
                                    pass
                        elif old_qty != qty:
                            updated += 1
                            stock_quantity_changes.append(
                                f"{product.name[:40]} ({old_qty} → {qty})"
                            )

                session.commit()

        total_checked = len(id_map)
        print(f"[Silverbene Stock Agent] Stock: checked={total_checked} updated={updated} "
              f"out_of_stock={deactivated} restocked={reactivated}")

        # ── Step 4: Refresh sizes for ALL categories ──────────────────────────
        sizes_updated, sizes_detail = _refresh_product_sizes(sb)

        # ── Step 5: Write to AgentMemory ──────────────────────────────────────
        result = {
            "checked": total_checked,
            "updated": updated,
            "deactivated": deactivated,
            "reactivated": reactivated,
            "sizes_updated": sizes_updated,
            "newly_outofstock": newly_outofstock,
            "newly_reactivated": newly_reactivated,
        }
        try:
            from app.models.agent import AgentMemory
            with Session(engine) as session:
                session.add(AgentMemory(
                    agent_name="silverbene_stock_agent",
                    memory_type="sync_run",
                    content=json.dumps({
                        "timestamp": datetime.utcnow().isoformat(),
                        **result,
                        "out_of_stock": newly_outofstock[:5],
                        "restocked": newly_reactivated[:5],
                        "sizes_detail": sizes_detail[:5],
                    }),
                    confidence=0.9
                ))
                session.commit()
        except Exception as e:
            print(f"[Silverbene Stock Agent] Memory write error: {e}")

        # ── Step 6: Nervous system signals ───────────────────────────────────
        try:
            from app.agents.nervous_system import emit
            emit(signal_type="STOCK_SYNC_COMPLETE", sender="silverbene_stock_agent",
                 payload=result, priority=8)
            for name in newly_outofstock:
                emit(signal_type="STOCK_OUT", sender="silverbene_stock_agent",
                     payload={"product_name": name}, priority=3)
            for name in newly_reactivated:
                emit(signal_type="STOCK_RESTORED", sender="silverbene_stock_agent",
                     payload={"product_name": name}, priority=6)
        except Exception as e:
            print(f"[Silverbene Stock Agent] Signal error: {e}")

        # ── Step 7: Email Dennis if ANYTHING changed ──────────────────────────
        any_change = (
            deactivated > 0 or reactivated > 0 or
            updated > 0 or sizes_updated > 0
        )
        if any_change:
            _aria_sync_report(
                total_checked=total_checked,
                updated=updated,
                deactivated=deactivated,
                reactivated=reactivated,
                sizes_updated=sizes_updated,
                newly_outofstock=newly_outofstock,
                newly_reactivated=newly_reactivated,
                stock_quantity_changes=stock_quantity_changes,
                sizes_detail=sizes_detail,
            )

        return result

    except Exception as e:
        import traceback
        print(f"[Silverbene Stock Agent] Error: {e}")
        traceback.print_exc()
        return {"error": str(e)}


def _refresh_product_sizes(sb) -> tuple:
    """
    Re-fetch Silverbene data for every product that is missing sizes or
    flagged needs_length_review, across ALL categories.

    Returns (count_updated, list_of_detail_strings).

    Categories handled:
      Rings     — ring sizes (e.g. "6", "7", "8", "US 7")
      Necklaces — chain lengths converted to "450mm / 18\"" chips
      Bracelets — bracelet sizes (e.g. "16cm", "17cm", "S", "M")
      Anklets   — anklet sizes  (e.g. "20cm", "22cm")
      Earrings  — size if present (often none)
      Ear Cuffs — size if present
    """
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        adapter = SilverbeneAdapter()

        with Session(engine) as session:
            # Products missing sizes OR flagged for review, across all categories
            needs_refresh = session.exec(
                select(Product).where(
                    Product.supplier_name == "Silverbene",
                    Product.is_active == True,
                    (Product.sizes == None) | (Product.needs_length_review == True),
                )
            ).all()

        if not needs_refresh:
            print("[Silverbene Stock Agent] All product sizes are up to date")
            return 0, []

        print(f"[Silverbene Stock Agent] Refreshing sizes for {len(needs_refresh)} products "
              f"across all categories")

        fixed = 0
        detail = []

        for p in needs_refresh:
            sku = p.cj_product_id
            if not sku:
                continue

            fresh = sb.get_by_sku(sku)
            if not fresh:
                continue

            options = fresh.get("_options", [])
            sizes_list, _ = adapter._extract_variants(options)

            if sizes_list:
                with Session(engine) as session:
                    prod = session.get(Product, p.id)
                    if prod:
                        old_sizes = prod.sizes
                        prod.sizes = json.dumps(sizes_list)
                        prod.needs_length_review = False
                        session.add(prod)
                        session.commit()
                fixed += 1
                detail.append(
                    f"{p.category} — {p.name[:45]}: {sizes_list}"
                )
                print(f"[Silverbene Stock Agent] Sizes updated [{p.category}] "
                      f"{p.name[:45]} → {sizes_list}")

        if fixed:
            print(f"[Silverbene Stock Agent] Sizes refreshed: {fixed} products updated")

        return fixed, detail

    except Exception as e:
        print(f"[Silverbene Stock Agent] Size refresh error: {e}")
        return 0, []


def _aria_sync_report(total_checked, updated, deactivated, reactivated,
                      sizes_updated, newly_outofstock, newly_reactivated,
                      stock_quantity_changes, sizes_detail):
    """
    ARIA reviews the full sync results and emails Dennis with everything
    that changed — stock levels, out-of-stock alerts, restocks, and size updates.
    """
    try:
        from app.agents.aria_intelligence import aria_think
        from app.agents.aria_memory import store_episode
        from app.agents.email_partner import send_email

        # Build a clear situation summary for ARIA
        parts = [
            f"Silverbene 6-hour sync completed. Checked {total_checked} products.",
        ]

        if deactivated > 0:
            names = "\n".join(f"  - {n}" for n in newly_outofstock[:10])
            parts.append(
                f"\n{deactivated} product(s) are now OUT OF STOCK at Silverbene "
                f"(shown as 'Out of Stock' in store):\n{names}"
            )

        if reactivated > 0:
            names = "\n".join(f"  - {n}" for n in newly_reactivated[:10])
            parts.append(
                f"\n{reactivated} product(s) came BACK IN STOCK and are now visible:\n{names}"
            )

        if updated > 0:
            changes = "\n".join(f"  - {c}" for c in stock_quantity_changes[:10])
            parts.append(
                f"\n{updated} product(s) had their stock quantity updated:\n{changes}"
            )

        if sizes_updated > 0:
            items = "\n".join(f"  - {d}" for d in sizes_detail[:10])
            parts.append(
                f"\n{sizes_updated} product(s) had size/length data refreshed from Silverbene:\n{items}"
            )

        parts.append(
            "\nPlease summarise these changes for Dennis in a clean, confident store-owner email. "
            "Use Mikisi brand tone — empowering, elegant, direct. "
            "If products went out of stock, suggest finding replacements. "
            "If sizes were updated, mention the store is now showing accurate sizing."
        )

        situation = "\n".join(parts)

        urgency = "high" if deactivated > 3 else "medium" if (deactivated > 0 or reactivated > 0) else "low"
        result = aria_think(situation=situation, urgency=urgency)

        store_episode(
            event=f"Sync: {deactivated} OOS, {reactivated} restocked, {updated} qty changes, {sizes_updated} sizes updated",
            context=situation[:300],
            decision="ARIA sent sync summary to Dennis",
            outcome="sync_reported",
            significance="medium" if deactivated > 0 else "low"
        )

        dennis_email = os.getenv("DENNIS_EMAIL")
        if dennis_email and result:
            email_data = result.get("email_to_dennis", {})
            subject = email_data.get(
                "subject",
                f"Mikisi Sync Update — {deactivated} OOS · {reactivated} restocked · {sizes_updated} sizes refreshed"
            )
            body = email_data.get("body", "")
            if body:
                send_email(dennis_email, subject, body, is_html=True)
                print(f"[Silverbene Stock Agent] Email sent to Dennis via ARIA")
            else:
                print(f"[Silverbene Stock Agent] ARIA returned no email body")

    except Exception as e:
        print(f"[Silverbene Stock Agent] ARIA report error: {e}")
