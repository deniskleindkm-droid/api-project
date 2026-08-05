"""
DHL Monitor
Polls hello@mikisi.co inbox every 2 hours for emails sent directly by DHL
(not by Silverbene) -- e.g. "your shipment is on its way" and "On Demand
Delivery" confirmations. These exist because the Silverbene order payload
intentionally gives DHL our own contact info, never the customer's (see
[[project_customer_phone_not_masked_decision]] and silverbene_adapter.py's
place_order) -- so DHL's own notifications land with us, not the customer,
and the customer never sees Silverbene's or DHL's name directly.

This agent's only job is to keep OrderTracking's DHL-side fields current:
  - tracking_number / carrier / status, for orders Silverbene ships via DHL
    without ever sending its own shipping_notification email (this is the
    common case -- see order #22, 2026-08-05, where no Silverbene email
    ever arrived, only DHL's).
  - dhl_odd_link -- the "On Demand Delivery" portal URL from DHL's email,
    which is what lets a delivery preference actually get applied (see
    tracking_agent.maybe_send_delivery_relay_alert).

Matching a DHL email back to an order is harder than for Silverbene mail:
DHL has no concept of our internal order id or Silverbene's cj_order_id.
The only reliable signal is the delivery address printed in the email body,
matched against Order.shipping_address. A waybill number, once seen once,
becomes the reliable key for any later email about the same shipment.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import json
import email
import imaplib
import anthropic
from email.header import decode_header
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order, OrderTracking

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

_DHL_SENDERS = ["dhl"]


def _imap_connect():
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_password:
        print("[DHLMonitor] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set")
        return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, gmail_password)
        return mail
    except Exception as e:
        print(f"[DHLMonitor] IMAP connect error: {e}")
        return None


def _get_email_parts(msg) -> tuple[str, str]:
    """
    Returns (plain_text_for_llm, raw_html) -- the plain text has tags
    stripped for cheap/clean LLM classification, but link extraction needs
    the raw HTML since anchor hrefs (the actual DHL portal URL) don't
    survive tag-stripping the way visible "click here" text does.
    """
    html_parts, plain_parts = [], []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            try:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                text = payload.decode(charset, errors="replace")
                if ct == "text/html":
                    html_parts.append(text)
                elif ct == "text/plain":
                    plain_parts.append(text)
            except Exception:
                pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            text = msg.get_payload(decode=True).decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)
        except Exception:
            pass

    raw_html = "\n".join(html_parts)
    combined = raw_html + "\n" + "\n".join(plain_parts)
    plain_text = re.sub(r'<[^<]+?>', ' ', combined)
    plain_text = re.sub(r'\s+', ' ', plain_text).strip()
    return plain_text, raw_html


_LINK_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _extract_links(raw_html: str) -> list[dict]:
    """Pulls (anchor text, href) pairs out of the raw HTML so the LLM can
    pick out which link is the actual On Demand Delivery / tracking portal --
    "click here" as visible text is useless without the href behind it."""
    links = []
    for href, text in _LINK_RE.findall(raw_html or ""):
        clean_text = re.sub(r'<[^<]+?>', ' ', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        if href.startswith("http"):
            links.append({"text": clean_text[:80], "href": href})
    return links


def _classify_dhl_email(subject: str, body: str, links: list[dict]) -> dict:
    """
    Falls back to {"type": "other"} on any parse failure -- one malformed
    LLM response shouldn't take down the whole scan.
    """
    links_desc = "\n".join(f'- "{l["text"]}" -> {l["href"]}' for l in links[:15]) or "(none found)"
    prompt = f"""You're reading an email sent by DHL Express to our operations inbox (hello@mikisi.co) about a shipment we booked on a customer's behalf. The customer never sees this inbox.

Subject: {subject}

Body:
{body[:3000]}

Links found in the email:
{links_desc}

Classify this email and extract details. Return ONLY valid JSON, no markdown fences:
{{
  "type": "shipment_notice" | "delivery_instructions_confirmation" | "other",
  "waybill_number": "<the waybill/tracking number if mentioned, else null>",
  "delivery_street": "<the delivery street address printed in the email, else null>",
  "delivery_postal_code": "<the delivery postal/zip code printed in the email, else null>",
  "odd_link": "<the href from the Links list that is the On Demand Delivery / delivery options / track shipment portal link, else null>"
}}

"shipment_notice" = a first notification that a shipment is on its way with an ETA.
"delivery_instructions_confirmation" = confirms delivery preferences that were set (e.g. "Your Updated Delivery Details", "Instruction You Gave Us")."""
    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r'^```(json)?|```$', '', text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"[DHLMonitor] Classification error: {e}")
        return {"type": "other"}


def _find_matching_tracking(waybill_number: str, delivery_street: str, delivery_postal_code: str) -> "OrderTracking | None":
    """
    Prefers an exact waybill match (a later email about an already-known
    shipment). Falls back to matching the delivery address against Order.
    shipping_address for orders DHL/Silverbene hasn't given us a tracking
    number for yet -- the only correlation key available on a brand-new
    waybill, since DHL has no concept of our order id.
    """
    with Session(engine) as session:
        if waybill_number:
            exact = session.exec(
                select(OrderTracking).where(OrderTracking.tracking_number == str(waybill_number).strip())
            ).first()
            if exact:
                print(f"[DHLMonitor] Matched order {exact.order_id} via exact waybill={waybill_number}")
                return exact

        candidates = session.exec(
            select(OrderTracking).where(
                OrderTracking.supplier_name == "Silverbene",
                OrderTracking.tracking_number.is_(None),
                OrderTracking.status.in_(["pending", "processing"]),
            )
        ).all()

        if not candidates:
            return None

        needle = (delivery_postal_code or delivery_street or "").strip()
        if needle:
            for t in candidates:
                order = session.get(Order, t.order_id)
                if order and needle.lower() in (order.shipping_address or "").lower():
                    print(f"[DHLMonitor] Matched order {t.order_id} via address match on {needle!r}")
                    return t

        if len(candidates) == 1:
            print(f"[DHLMonitor] Single unmatched Silverbene order — assuming order {candidates[0].order_id}")
            return candidates[0]

        print(f"[DHLMonitor] {len(candidates)} unmatched orders but none matched address")
        return None


def run_dhl_monitor():
    """Main entry point -- called by the scheduler every 2 hours."""
    print(f"\n[DHLMonitor] Scanning inbox — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    result = {"connected": False, "processed": 0, "matched": [], "unmatched": []}

    mail = _imap_connect()
    if not mail:
        return result
    result["connected"] = True

    try:
        mail.select("INBOX")
        _, msgs = mail.search(None, '(UNSEEN FROM "dhl")')
        email_ids = msgs[0].split() if msgs[0] else []

        if not email_ids:
            print("[DHLMonitor] No unread DHL emails")
            return result

        print(f"[DHLMonitor] Found {len(email_ids)} unread DHL email(s)")

        for eid in email_ids:
            try:
                _, data = mail.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])

                raw_subject = msg.get("Subject", "")
                decoded = decode_header(raw_subject)[0]
                subject = decoded[0].decode(decoded[1] or "utf-8") if isinstance(decoded[0], bytes) else decoded[0]

                sender = msg.get("From", "")
                body, raw_html = _get_email_parts(msg)
                result["processed"] += 1

                if not any(s in sender.lower() for s in _DHL_SENDERS):
                    continue

                print(f"[DHLMonitor] Email: from={sender!r} subject={subject!r}")

                links = _extract_links(raw_html)
                classification = _classify_dhl_email(subject, body, links)
                etype = classification.get("type", "other")

                if etype == "other":
                    print(f"[DHLMonitor] Recognized as 'other' — left unread for manual review")
                    result["unmatched"].append({"subject": subject, "type": "other"})
                    continue

                waybill = (classification.get("waybill_number") or "").strip() or None
                odd_link = (classification.get("odd_link") or "").strip() or None

                tracking = _find_matching_tracking(
                    waybill,
                    classification.get("delivery_street"),
                    classification.get("delivery_postal_code"),
                )
                if not tracking:
                    print("[DHLMonitor] Could not match to an order — left unread")
                    result["unmatched"].append({"subject": subject, "waybill": waybill})
                    continue

                with Session(engine) as session:
                    t = session.get(OrderTracking, tracking.id)
                    if waybill and not t.tracking_number:
                        t.tracking_number = waybill
                        t.carrier = "DHL"
                        t.status = "dispatched"
                        t.shipped_at = t.shipped_at or datetime.utcnow()
                    if odd_link:
                        t.dhl_odd_link = odd_link
                    session.add(t)
                    session.commit()
                    session.refresh(t)
                    tracking = t

                    order = session.get(Order, tracking.order_id)
                    if order and waybill:
                        order.tracking_number = waybill
                        if order.status == "processing":
                            order.status = "shipped"
                        session.add(order)
                        session.commit()

                if odd_link:
                    from app.agents.tracking_agent import maybe_send_delivery_relay_alert
                    maybe_send_delivery_relay_alert(tracking.id)

                mail.store(eid, "+FLAGS", "\\Seen")
                result["matched"].append({"order_id": tracking.order_id, "type": etype, "waybill": waybill})

            except Exception as e:
                import traceback
                print(f"[DHLMonitor] Error processing email {eid}: {e}")
                traceback.print_exc()

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    print(f"[DHLMonitor] Done — {len(result['matched'])} matched, {len(result['unmatched'])} unmatched")
    return result
