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

        # ── Step 2: Build option_id → product map (all variants) ────────────────
        # option_map: option_id_str → product_id
        # product_variants: product_id → [option_id_str, ...]
        option_map = {}
        product_variants = {}  # product_id → list of all option_ids

        for p in all_products:
            ids_for_product = []
            if p.cj_sku:
                oid = str(p.cj_sku)
                option_map[oid] = p.id
                ids_for_product.append(oid)
            # Pull every variant's option_id so we check all sizes
            if p.variants:
                try:
                    for v in json.loads(p.variants):
                        oid = str(v.get("option_id", ""))
                        if oid and oid not in option_map:
                            option_map[oid] = p.id
                            ids_for_product.append(oid)
                except Exception:
                    pass
            if ids_for_product:
                product_variants[p.id] = ids_for_product

        if not option_map:
            print("[Silverbene Stock Agent] No option_ids found — cannot check stock")
            return {"checked": 0, "updated": 0, "deactivated": 0, "reactivated": 0, "sizes_updated": 0}

        print(f"[Silverbene Stock Agent] Checking {len(option_map)} option_ids across {len(product_variants)} products")

        # ── Step 3: Query every option_id, collect results ───────────────────
        # live_stock: option_id → qty  (only option_ids we got a response for)
        live_stock = {}

        for single_id in list(option_map.keys()):
            resp = sb._get("/api/dropshipping/option_qty", {"option_id": single_id})
            if not isinstance(resp, dict) or resp.get("code") != 0:
                continue
            stock_data = resp.get("data", [])
            if not isinstance(stock_data, list) or not stock_data:
                continue
            item = stock_data[0] if isinstance(stock_data[0], dict) else {}
            qty = int(item.get("qty", item.get("qyt", 0)) or 0)
            live_stock[single_id] = qty

        # ── Step 4: Aggregate per product and apply changes ──────────────────
        updated = 0
        deactivated = 0
        reactivated = 0
        newly_outofstock = []
        newly_reactivated = []
        stock_quantity_changes = []

        for product_id, option_ids in product_variants.items():
            checked = {oid: live_stock[oid] for oid in option_ids if oid in live_stock}
            if not checked:
                # No response at all → record miss
                _record_miss(product_id)
                continue

            total_qty = sum(checked.values())

            with Session(engine) as session:
                product = session.get(Product, product_id)
                if not product:
                    continue

                # Update variants JSON with live stock per option_id
                if product.variants:
                    try:
                        variants_data = json.loads(product.variants)
                        changed_variants = False
                        for v in variants_data:
                            oid = str(v.get("option_id", ""))
                            if oid in checked:
                                v["qty"] = checked[oid]
                                changed_variants = True
                        if changed_variants:
                            product.variants = json.dumps(variants_data)
                    except Exception:
                        pass

                if total_qty == 0:
                    # A valid response (even qty=0) proves this product/option still
                    # exists at Silverbene — it's out of stock, not discontinued.
                    # Reset any pending miss count so the discontinuation agent stops
                    # re-flagging it every cycle forever; previously this only reset
                    # when stock came back above zero, so a product that settled into
                    # a stable "confirmed, but 0 stock" state stayed stuck at whatever
                    # miss count it last had, notified on every sync with no resolution.
                    was_missed = product.sync_miss_count > 0
                    changed = False
                    if product.stock != 0:
                        product.stock = 0
                        product.is_active = True
                        if product.is_published:
                            product.is_published = False
                            product.stock_auto_unpublished = True
                        changed = True
                        deactivated += 1
                        newly_outofstock.append(product.name[:60])
                        print(f"[Silverbene Stock Agent] Out of stock → unpublished: {product.name[:50]}")
                        if product.pinterest_pin_id:
                            try:
                                from app.agents.pinterest_agent import update_product_availability
                                update_product_availability(product.id, False)
                            except Exception:
                                pass
                    if was_missed:
                        product.sync_miss_count = 0
                        changed = True
                        print(f"[Silverbene Stock Agent] Confirmed still exists (qty=0) — miss count reset: {product.name[:50]}")
                    if changed:
                        session.add(product)
                        session.commit()
                else:
                    old_qty = product.stock
                    was_oos = product.stock == 0
                    was_missed = product.sync_miss_count > 0
                    product.stock = total_qty
                    product.is_active = True
                    product.sync_miss_count = 0
                    if was_oos and product.stock_auto_unpublished:
                        product.stock_auto_unpublished = False
                    session.add(product)
                    session.commit()

                    if was_missed:
                        try:
                            from app.agents.silverbene_discontinuation_agent import handle_recovery
                            handle_recovery(product.id, {"stock": total_qty, "final_price": product.final_price})
                        except Exception as e:
                            print(f"[Silverbene Stock Agent] Recovery handoff error: {e}")

                    if was_oos:
                        reactivated += 1
                        newly_reactivated.append(product.name[:60])
                        print(f"[Silverbene Stock Agent] Back in stock → republished: {product.name[:50]}")
                        if product.pinterest_pin_id:
                            try:
                                from app.agents.pinterest_agent import update_product_availability
                                update_product_availability(product.id, True)
                            except Exception:
                                pass
                    elif old_qty != total_qty:
                        updated += 1
                        stock_quantity_changes.append(
                            f"{product.name[:40]} ({old_qty} → {total_qty})"
                        )

        total_checked = len(product_variants)
        print(f"[Silverbene Stock Agent] Stock: checked={total_checked} updated={updated} "
              f"out_of_stock={deactivated} restocked={reactivated}")

        # ── Step 4: Run discontinuation agent on any products with missed syncs ──
        try:
            from app.agents.silverbene_discontinuation_agent import run_discontinuation_agent
            run_discontinuation_agent()
        except Exception as e:
            print(f"[Silverbene Stock Agent] Discontinuation agent error: {e}")

        # ── Step 5: Refresh sizes for ALL categories ──────────────────────────
        sizes_updated, sizes_detail = _refresh_product_sizes(sb)

        # ── Step 5b: Correct earring stud/hoop naming against Silverbene's raw title ──
        names_updated, names_detail = _refresh_earring_names(sb)

        # ── Step 5: Write to AgentMemory ──────────────────────────────────────
        result = {
            "checked": total_checked,
            "updated": updated,
            "deactivated": deactivated,
            "reactivated": reactivated,
            "sizes_updated": sizes_updated,
            "names_updated": names_updated,
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
                        "names_detail": names_detail[:5],
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
            updated > 0 or sizes_updated > 0 or names_updated > 0
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
                names_updated=names_updated,
                names_detail=names_detail,
            )

        return result

    except Exception as e:
        import traceback
        print(f"[Silverbene Stock Agent] Error: {e}")
        traceback.print_exc()
        return {"error": str(e)}


def _record_miss(product_id):
    """Increment sync_miss_count and unpublish on first miss."""
    if not product_id:
        return
    try:
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if not product:
                return
            product.sync_miss_count = (product.sync_miss_count or 0) + 1
            if product.sync_miss_count == 1 and product.is_published:
                product.is_published = False
                product.stock_auto_unpublished = False  # discontinuation, not OOS
                print(f"[Silverbene Stock Agent] Miss 1 — unpublished: {product.name[:50]}")
            session.add(product)
            session.commit()
    except Exception as e:
        print(f"[Silverbene Stock Agent] Miss record error: {e}")


def _lacks_real_length(sizes_list) -> bool:
    """
    True if no chip in the list carries an actual measurement — e.g. a bare
    ["Adjustable"] or ["One Size / Adjustable"] with no inch/cm figure attached.
    A vague label isn't a size; a bracelet or necklace always has a real
    physical length even when we haven't captured it yet.
    """
    if not sizes_list:
        return True
    if any(s == "Pendant Only" for s in sizes_list):
        return False
    return not any(re.search(r'\d', s) for s in sizes_list)


def _refresh_product_sizes(sb) -> tuple:
    """
    Re-fetch Silverbene data for every product that is missing sizes,
    has only a vague adjustable-with-no-measurement label, or is flagged
    needs_length_review, across ALL categories.

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
            # Products missing sizes OR flagged for review, across all categories.
            # Also include necklaces with a single plain size (e.g. ["18\""]) that
            # may be adjustable — re-verify against live Silverbene description.
            all_sb = session.exec(
                select(Product).where(
                    Product.supplier_name == "Silverbene",
                    Product.is_active == True,
                )
            ).all()

        needs_refresh = []
        for p in all_sb:
            if p.sizes is None or p.needs_length_review:
                needs_refresh.append(p)
                continue
            if p.category in ("Bracelets", "Necklaces", "Anklets"):
                try:
                    s = json.loads(p.sizes)
                except Exception:
                    s = []
                # Bare "Adjustable"/"One Size" with no digits — retry for real length.
                if _lacks_real_length(s if isinstance(s, list) else []):
                    needs_refresh.append(p)
                    continue
            # Re-check necklaces with a single plain-inch size (could be wrong)
            if p.category == "Necklaces":
                try:
                    import json as _json
                    s = _json.loads(p.sizes)
                    if len(s) == 1 and s[0] not in ("Pendant Only",) and "Adjustable" not in s[0] and '"' in s[0]:
                        needs_refresh.append(p)
                except Exception:
                    pass

        if not needs_refresh:
            print("[Silverbene Stock Agent] All product sizes are up to date")
            return 0, []

        print(f"[Silverbene Stock Agent] Refreshing sizes for {len(needs_refresh)} products "
              f"across all categories")

        fixed = 0
        detail = []

        for p in needs_refresh:
            try:
                sku = p.cj_product_id
                if not sku:
                    continue

                from app.agents.suppliers.silverbene_adapter import _parse_chain_length_from_desc
                from app.agents.suppliers.silverbene_adapter import _extract_bracelet_info_from_desc
                from app.agents.suppliers.silverbene_adapter import _is_pendant_only

                def _desc_sizes(raw_desc: str, category: str):
                    if category == "Bracelets":
                        return _extract_bracelet_info_from_desc(raw_desc)["sizes"]
                    return _parse_chain_length_from_desc(raw_desc)

                # Primary: fetch by SKU
                fresh = sb.get_by_sku(sku)
                sizes_list = None
                raw_desc = ""

                if fresh and isinstance(fresh, dict):
                    raw_desc = fresh.get("description", "") or ""
                    # Pendant-only: no chain included — flag immediately
                    if p.category == "Necklaces" and _is_pendant_only(raw_desc):
                        sizes_list = ["Pendant Only"]
                    else:
                        options = fresh.get("_options", [])
                        if isinstance(options, list):
                            sizes_list, _ = adapter._extract_variants(options, category=p.category)
                        # Chain length always comes from desc material-info section
                        if not sizes_list:
                            sizes_list = _desc_sizes(raw_desc, p.category) or None

                # Fallback: search by product name via date-window endpoint
                if not sizes_list:
                    keywords = " ".join(p.name.lower().split()[:4])
                    results = sb.search(keyword=keywords, limit=20)
                    for r in results:
                        if r.get("supplier_product_id") == sku:
                            raw_desc = r.get("description", "") or ""
                            if p.category == "Necklaces" and _is_pendant_only(raw_desc):
                                sizes_list = ["Pendant Only"]
                            else:
                                opts = r.get("_options", [])
                                if isinstance(opts, list):
                                    sizes_list, _ = adapter._extract_variants(opts, category=p.category)
                                if not sizes_list:
                                    sizes_list = _desc_sizes(raw_desc, p.category) or None
                            break

                existing = json.loads(p.sizes) if p.sizes else []
                still_lacking = _lacks_real_length(sizes_list) if sizes_list else True

                if sizes_list and sizes_list != existing:
                    with Session(engine) as session:
                        prod = session.get(Product, p.id)
                        if prod:
                            prod.sizes = json.dumps(sizes_list)
                            prod.needs_length_review = still_lacking
                            session.add(prod)
                            session.commit()
                    fixed += 1
                    detail.append(
                        f"{p.category} — {p.name[:45]}: {existing} → {sizes_list}"
                        + (" [still no real length — flagged for review]" if still_lacking else "")
                    )
                    print(f"[Silverbene Stock Agent] Sizes updated [{p.category}] "
                          f"{p.name[:45]} → {sizes_list}")
                elif still_lacking and not p.needs_length_review:
                    # Live re-fetch found nothing better — flag it so it surfaces
                    # in Dennis's daily digest instead of silently retrying forever.
                    with Session(engine) as session:
                        prod = session.get(Product, p.id)
                        if prod:
                            prod.needs_length_review = True
                            session.add(prod)
                            session.commit()
                    print(f"[Silverbene Stock Agent] No real length found [{p.category}] "
                          f"{p.name[:45]} — flagged needs_length_review")
            except Exception as e:
                print(f"[Silverbene Stock Agent] Size refresh skipped for {p.name[:45]}: {e}")
                continue

        if fixed:
            print(f"[Silverbene Stock Agent] Sizes refreshed: {fixed} products updated")

        return fixed, detail

    except Exception as e:
        print(f"[Silverbene Stock Agent] Size refresh error: {e}")
        return 0, []


def _refresh_earring_names(sb) -> tuple:
    """
    Re-check every live Silverbene earring's name AND Mikisi description against
    Silverbene's raw title, falling back to its raw description when the title
    is silent on style (many Silverbene titles omit stud/hoop but the
    description's "Category:"/"Style:"/"Earring Type:" fields state it
    explicitly). Corrects stud/hoop mislabeling wherever it appears and
    guarantees the word "Earring" appears in the name — Silverbene's own text
    is the ground truth, never guessed. Only that one word is ever swapped in
    the description; everything else ARIA wrote (tone, material, structure) —
    and is_published — is left untouched.

    Returns (count_updated, list_of_detail_strings).
    """
    try:
        from app.agents.bulk_import_agent import (
            _enforce_earring_style,
            _enforce_earring_description_style,
            _ensure_category_in_name,
        )

        with Session(engine) as session:
            earrings = session.exec(
                select(Product).where(
                    Product.supplier_name == "Silverbene",
                    Product.category == "Earrings",
                    Product.is_active == True,
                )
            ).all()

        if not earrings:
            return 0, []

        fixed = 0
        detail = []

        for p in earrings:
            sku = p.cj_product_id
            if not sku:
                continue
            try:
                fresh = sb.get_by_sku(sku, category="Earrings")
                raw_name = fresh.get("name", "") if isinstance(fresh, dict) else ""
                raw_desc = fresh.get("description", "") if isinstance(fresh, dict) else ""
                if not raw_name:
                    continue

                corrected_name = _enforce_earring_style(p.name, raw_name, "Earrings", raw_desc)
                corrected_name = _ensure_category_in_name(corrected_name, "Earrings")[:100]
                corrected_desc = _enforce_earring_description_style(p.description, raw_name, "Earrings", raw_desc)

                name_changed = corrected_name != p.name
                desc_changed = corrected_desc != p.description

                if name_changed or desc_changed:
                    old_name = p.name
                    with Session(engine) as session:
                        prod = session.get(Product, p.id)
                        if prod:
                            prod.name = corrected_name
                            prod.description = corrected_desc
                            session.add(prod)
                            session.commit()
                    fixed += 1
                    if name_changed:
                        detail.append(f"{old_name} -> {corrected_name}")
                        print(f"[Silverbene Stock Agent] Earring name corrected: {old_name} -> {corrected_name}")
                    if desc_changed:
                        detail.append(f"{old_name}: description stud/hoop wording corrected")
                        print(f"[Silverbene Stock Agent] Earring description wording corrected: {old_name}")
            except Exception as e:
                print(f"[Silverbene Stock Agent] Earring name check skipped for {p.name[:45]}: {e}")
                continue

        return fixed, detail

    except Exception as e:
        print(f"[Silverbene Stock Agent] Earring name refresh error: {e}")
        return 0, []


def _aria_sync_report(total_checked, updated, deactivated, reactivated,
                      sizes_updated, newly_outofstock, newly_reactivated,
                      stock_quantity_changes, sizes_detail,
                      names_updated=0, names_detail=None):
    """
    ARIA reviews the full sync results and emails Dennis with everything
    that changed — stock levels, out-of-stock alerts, restocks, and size updates.
    """
    try:
        from app.agents.aria_intelligence import aria_think
        from app.agents.aria_memory import store_episode

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

        if names_updated > 0:
            items = "\n".join(f"  - {d}" for d in (names_detail or [])[:10])
            parts.append(
                f"\n{names_updated} earring name(s) corrected to match Silverbene's stud/hoop naming:\n{items}"
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

        # Email to Dennis disabled — every sync that changed anything (which is
        # most of them) was firing a separate email, flooding the inbox. The
        # episode is still logged above via store_episode() for the admin
        # sync report; ARIA's summary is available there instead of by email.
        print(f"[Silverbene Stock Agent] Sync summary logged (email suppressed)")

    except Exception as e:
        print(f"[Silverbene Stock Agent] ARIA report error: {e}")
