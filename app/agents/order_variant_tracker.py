"""
Order Variant Tracker
=====================
Verifies that every order line item sent to Silverbene matches exactly
what the customer selected (size + color).

Stage 1 — Immediate local check (runs inside the Stripe webhook):
  - Looks up the option_id we sent in product.variants
  - Compares the variant's actual size/color against what the customer chose
  - Stores the result in order_variant_check table
  - Emails hello@mikisi.co immediately if anything is wrong

Stage 2 — Silverbene-side confirmation (deferred):
  - Silverbene has no order query API as of 2026-07-06
  - The shipping monitor calls confirm_silverbene_shipped(silverbene_order_id)
    when a shipping email from Silverbene is received, setting
    silverbene_confirmed=True on the matching record
  - This proves Silverbene received and processed the order

Gap addressed:
  Without this tracker, a resolve_option_id() fallback (pass 4) would silently
  send the wrong variant to Silverbene with no visibility. This system catches
  every case where size/color routing was imperfect and alerts immediately.
"""

import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.order_variant_check import OrderVariantCheck
from app.agents.suppliers.silverbene_adapter import (
    COLOR_ATTRIBUTE_NAMES,
    _normalize_size_for_match,
    _normalize_color_final,
    _clean_color_value,
    _COLOR_LABEL_REVERSE,
    parse_necklace_length,
)


# ── Public entry points ────────────────────────────────────────────────────────

def check_order_item(
    *,
    order_id: int,
    silverbene_order_id: str,
    product_id: int,
    product_name: str,
    variants_json: str,
    option_id_sent: str,
    resolve_pass: str,
    selected_size: str,
    selected_color: str,
    customer_email: str,
    customer_name: str,
) -> OrderVariantCheck:
    """
    Stage 1 check. Call immediately after Silverbene confirms the order.
    Returns the saved OrderVariantCheck record.
    """
    record = _run_check(
        order_id=order_id,
        silverbene_order_id=silverbene_order_id,
        product_id=product_id,
        product_name=product_name,
        variants_json=variants_json,
        option_id_sent=option_id_sent,
        resolve_pass=resolve_pass,
        selected_size=selected_size,
        selected_color=selected_color,
        customer_email=customer_email,
        customer_name=customer_name,
    )

    # Alert Dennis on anything that isn't a clean exact match
    needs_alert = record.match_status not in ("ok", "no_variants")
    if needs_alert:
        _send_alert(record)
        with Session(engine) as session:
            r = session.get(OrderVariantCheck, record.id)
            if r:
                r.alerted = True
                session.add(r)
                session.commit()

    return record


def confirm_silverbene_shipped(silverbene_order_id: str):
    """
    Stage 2. Called by the shipping monitor when a Silverbene shipping email
    is received for this order. Marks the record as Silverbene-confirmed.
    """
    if not silverbene_order_id:
        return
    with Session(engine) as session:
        records = session.exec(
            select(OrderVariantCheck).where(
                OrderVariantCheck.silverbene_order_id == silverbene_order_id
            )
        ).all()
        for r in records:
            r.silverbene_confirmed = True
            r.silverbene_confirmed_at = datetime.utcnow()
            session.add(r)
        session.commit()
        if records:
            print(f"[VariantTracker] Silverbene confirmed shipment for order {silverbene_order_id} "
                  f"({len(records)} line item(s))")


# ── Core logic ─────────────────────────────────────────────────────────────────

def _run_check(*, order_id, silverbene_order_id, product_id, product_name,
               variants_json, option_id_sent, resolve_pass,
               selected_size, selected_color, customer_email, customer_name) -> OrderVariantCheck:

    record = OrderVariantCheck(
        order_id=order_id,
        silverbene_order_id=silverbene_order_id,
        product_id=product_id,
        product_name=product_name,
        customer_email=customer_email,
        customer_name=customer_name,
        selected_size=selected_size,
        selected_color=selected_color,
        option_id_sent=option_id_sent,
        resolve_pass=resolve_pass,
    )

    # No variant data at all — can't verify, but not an error
    if not variants_json:
        record.match_status = "no_variants"
        _save(record)
        return record

    try:
        variants = json.loads(variants_json)
    except Exception:
        record.match_status = "no_variants"
        _save(record)
        return record

    if not variants:
        record.match_status = "no_variants"
        _save(record)
        return record

    # Find the variant that was actually sent
    sent_variant = next(
        (v for v in variants if str(v.get("option_id", "")) == str(option_id_sent)),
        None
    )

    if sent_variant is None:
        record.match_status = "not_found"
        record.mismatch_detail = (
            f"option_id {option_id_sent} not found in product variants. "
            f"DB may be stale — run a product refresh."
        )
        _save(record)
        return record

    # Extract what the sent variant actually is
    attrs = sent_variant.get("attribute") or sent_variant.get("attributes") or []
    actual_size  = _extract_size(attrs)
    actual_color = _extract_color(attrs)

    record.variant_size  = actual_size
    record.variant_color = actual_color

    # If the customer made no selection, there's nothing to check
    has_size_selection  = bool((selected_size  or "").strip())
    has_color_selection = bool((selected_color or "").strip())

    if not has_size_selection and not has_color_selection:
        # Single-variant product or customer didn't need to choose
        record.match_status = "ok"
        _save(record)
        return record

    # Compare selections
    size_ok  = _size_matches(selected_size,  actual_size)  if has_size_selection  else True
    color_ok = _color_matches(selected_color, actual_color) if has_color_selection else True

    # fallback_used (pass 4) means we couldn't match at all — always flag
    if resolve_pass == "fallback" and (has_size_selection or has_color_selection):
        record.match_status  = "fallback_used"
        record.mismatch_detail = (
            f"Could not find a variant matching "
            f"size={selected_size!r} color={selected_color!r}. "
            f"Sent first variant (id={option_id_sent}): "
            f"size={actual_size!r} color={actual_color!r}."
        )
    elif not size_ok and not color_ok:
        record.match_status  = "both_mismatch"
        record.mismatch_detail = (
            f"Customer chose size={selected_size!r} color={selected_color!r}. "
            f"Sent variant has size={actual_size!r} color={actual_color!r}."
        )
    elif not size_ok:
        record.match_status  = "size_mismatch"
        record.mismatch_detail = (
            f"Customer chose size={selected_size!r} but sent variant size={actual_size!r}. "
            f"Color matched ({actual_color!r})."
        )
    elif not color_ok:
        record.match_status  = "color_mismatch"
        record.mismatch_detail = (
            f"Customer chose color={selected_color!r} but sent variant color={actual_color!r}. "
            f"Size matched ({actual_size!r})."
        )
    else:
        record.match_status = "ok"

    _save(record)
    return record


# ── Attribute extraction ───────────────────────────────────────────────────────

def _extract_size(attrs: list) -> str | None:
    for a in attrs:
        name = (a.get("name") or "").lower().strip()
        val  = (a.get("value") or "").strip()
        if name in ("size", "ring size", "bracelet size", "anklet size"):
            normalized = _normalize_size_for_match(val)
            if not normalized and val:
                chips = parse_necklace_length(val)
                return chips[0] if chips else val
            return normalized
        if name in ("chain length", "length") and val:
            chips = parse_necklace_length(val)
            if chips:
                return chips[0]
    return None


def _extract_color(attrs: list) -> str | None:
    for a in attrs:
        name = (a.get("name") or "").lower().strip()
        val  = (a.get("value") or "").strip()
        if name in COLOR_ATTRIBUTE_NAMES:
            cleaned = _clean_color_value(val)
            return _normalize_color_final(cleaned, name) or None
    return None


# ── Match helpers ──────────────────────────────────────────────────────────────

def _size_matches(selected: str, actual: str) -> bool:
    if not selected or not actual:
        return True   # one side absent — can't falsify
    return _normalize_size_for_match(selected).lower() == _normalize_size_for_match(actual).lower()


def _color_matches(selected: str, actual: str) -> bool:
    if not selected or not actual:
        return True
    sel_lower = selected.lower().strip()
    act_lower = actual.lower().strip()
    if sel_lower == act_lower:
        return True
    # Reverse label map (e.g. display "Rose Gold" matches stored "Pink")
    candidates = _COLOR_LABEL_REVERSE.get(sel_lower, [])
    return act_lower in candidates


# ── Persistence ────────────────────────────────────────────────────────────────

def _save(record: OrderVariantCheck):
    try:
        with Session(engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
    except Exception as e:
        print(f"[VariantTracker] DB save error: {e}")


# ── Alert email ────────────────────────────────────────────────────────────────

def _send_alert(record: OrderVariantCheck):
    """
    One email per problem record. If multiple items in the same order have issues,
    payments.py batches them into one email via _send_batched_order_alert().
    This function is the single-item fallback (also used by tests).
    """
    try:
        from app.agents.email_partner import send_email
        admin = os.getenv("DENNIS_EMAIL", "hello@mikisi.co")

        status_label = {
            "size_mismatch":  "⚠ Size mismatch",
            "color_mismatch": "⚠ Color mismatch",
            "both_mismatch":  "⚠ Size + color mismatch",
            "fallback_used":  "⚠ Variant not matched — first variant used",
            "not_found":      "🚨 option_id not in variants DB",
        }.get(record.match_status, f"⚠ {record.match_status}")

        body = f"""
<div style="font-family:sans-serif;max-width:620px;margin:0 auto;padding:24px;">
<h2 style="color:#dc2626;margin:0 0 4px">{status_label}</h2>
<p style="color:#555;margin:0 0 20px">
  An order line item may have been routed to the wrong variant at Silverbene.
  Act before they ship.
</p>
<table style="border-collapse:collapse;width:100%;font-size:14px;">
  <tr style="background:#fef2f2;">
    <td style="padding:10px;font-weight:600;width:40%">Product</td>
    <td style="padding:10px">{record.product_name}</td>
  </tr>
  <tr><td style="padding:10px;color:#555">Customer</td>
      <td style="padding:10px">{record.customer_name or '—'} &lt;{record.customer_email or '—'}&gt;</td></tr>
  <tr style="background:#fef2f2;">
    <td style="padding:10px;color:#555">Customer selected</td>
    <td style="padding:10px">
      Size: <strong>{record.selected_size or '—'}</strong> &nbsp;·&nbsp;
      Color: <strong>{record.selected_color or '—'}</strong>
    </td>
  </tr>
  <tr><td style="padding:10px;color:#555">We sent to Silverbene</td>
      <td style="padding:10px">option_id <strong>{record.option_id_sent}</strong>
        (matched via: {record.resolve_pass})</td></tr>
  <tr style="background:#fef2f2;">
    <td style="padding:10px;color:#555">That option maps to</td>
    <td style="padding:10px">
      Size: <strong>{record.variant_size or '—'}</strong> &nbsp;·&nbsp;
      Color: <strong>{record.variant_color or '—'}</strong>
    </td>
  </tr>
  <tr><td style="padding:10px;color:#555">Detail</td>
      <td style="padding:10px;color:#b45309">{record.mismatch_detail or '—'}</td></tr>
  <tr style="background:#fef2f2;">
    <td style="padding:10px;color:#555">Order IDs</td>
    <td style="padding:10px">
      Mikisi: <strong>#{record.order_id}</strong> &nbsp;·&nbsp;
      Silverbene: <strong>{record.silverbene_order_id or 'pending'}</strong>
    </td>
  </tr>
</table>
<p style="margin-top:20px;color:#dc2626;font-weight:600">
  Contact Silverbene to correct this before it ships:<br>
  <a href="mailto:jackyli@silverbene.com">jackyli@silverbene.com</a> &nbsp;|&nbsp;
  WhatsApp +86 180 2239 4913
</p>
<p style="color:#aaa;font-size:11px;margin-top:16px">Mikisi Order Variant Tracker</p>
</div>"""

        send_email(admin, f"⚠ Variant Check Failed — {record.product_name[:40]}", body, is_html=True)
        print(f"[VariantTracker] Alert sent for order #{record.order_id} — {record.match_status}")
    except Exception as e:
        print(f"[VariantTracker] Alert email error: {e}")


def send_batched_order_alert(order_id: int, problems: list[OrderVariantCheck]):
    """
    Called from payments.py when multiple items in one order have issues.
    Sends one email covering all problem items grouped by status.
    """
    if not problems:
        return
    try:
        from app.agents.email_partner import send_email
        admin = os.getenv("DENNIS_EMAIL", "hello@mikisi.co")

        rows = ""
        for r in problems:
            status_label = {
                "size_mismatch":  "⚠ Wrong size",
                "color_mismatch": "⚠ Wrong color",
                "both_mismatch":  "⚠ Wrong size + color",
                "fallback_used":  "⚠ Variant unmatched",
                "not_found":      "🚨 option_id missing",
            }.get(r.match_status, r.match_status)
            rows += f"""
<tr style="border-bottom:1px solid #ffe4e6;">
  <td style="padding:10px 14px;font-weight:500">{r.product_name}</td>
  <td style="padding:10px 14px;color:#dc2626">{status_label}</td>
  <td style="padding:10px 14px">
    Chose: {r.selected_size or '—'} · {r.selected_color or '—'}<br>
    <span style="color:#555;font-size:12px">Sent id {r.option_id_sent} →
      {r.variant_size or '—'} · {r.variant_color or '—'}</span>
  </td>
</tr>"""

        cust = problems[0]
        body = f"""
<div style="font-family:sans-serif;max-width:640px;margin:0 auto;padding:24px;">
<h2 style="color:#dc2626;margin:0 0 4px">⚠ Variant Check Failed — Order #{order_id}</h2>
<p style="color:#555;margin:0 0 4px">
  Customer: <strong>{cust.customer_name or '—'}</strong>
  &lt;{cust.customer_email or '—'}&gt;
</p>
<p style="color:#555;margin:0 0 20px">
  Silverbene ref: <strong>{cust.silverbene_order_id or 'pending'}</strong>
</p>
<table style="border-collapse:collapse;width:100%;font-size:13px;">
  <tr style="background:#fef2f2;">
    <th style="padding:8px 14px;text-align:left">Product</th>
    <th style="padding:8px 14px;text-align:left">Issue</th>
    <th style="padding:8px 14px;text-align:left">Details</th>
  </tr>
  {rows}
</table>
<p style="margin-top:20px;color:#dc2626;font-weight:600">
  Contact Silverbene before they ship:<br>
  <a href="mailto:jackyli@silverbene.com">jackyli@silverbene.com</a> &nbsp;|&nbsp;
  WhatsApp +86 180 2239 4913
</p>
<p style="color:#aaa;font-size:11px;margin-top:16px">Mikisi Order Variant Tracker</p>
</div>"""

        send_email(admin, f"⚠ Variant Issues — Order #{order_id} ({len(problems)} item(s))", body, is_html=True)
        print(f"[VariantTracker] Batched alert sent for order #{order_id} — {len(problems)} problem(s)")
    except Exception as e:
        print(f"[VariantTracker] Batched alert error: {e}")
