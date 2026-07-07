"""
Silverbene Shipping Monitor
Polls hello@mikisi.co inbox via IMAP every 2 hours.
When Silverbene sends a shipping notification, this agent:
  1. Extracts the tracking number from the email
  2. Matches the email to an OrderTracking record via cj_order_id
  3. Automatically sends the Mikisi-branded shipping email to the real customer
  4. Marks the inbox email as read so it's never processed twice
"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import email
import imaplib
from email.header import decode_header
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order, OrderTracking


# ── Tracking number patterns ──────────────────────────────────────────────────
# Order matters: most specific first

_TRACKING_PATTERNS = [
    # USPS — 20-22 digit strings starting with 9
    (re.compile(r'\b(9[0-9]{19,21})\b'), "USPS"),
    # FedEx — 12 or 15 digits
    (re.compile(r'\b([0-9]{15})\b'), "FedEx"),
    (re.compile(r'\b([0-9]{12})\b'), "FedEx"),
    # EMS / postal — 2 letters + 9 digits + 2 letters (e.g. EA123456789US)
    (re.compile(r'\b([A-Z]{2}[0-9]{9}[A-Z]{2})\b'), "EMS"),
    # DHL — 10 digits
    (re.compile(r'\b([0-9]{10})\b'), "DHL"),
]

# Keywords in subject/body that identify a Silverbene shipping email
_SHIPPING_KEYWORDS = [
    "shipped", "dispatched", "tracking", "on its way",
    "has been sent", "order shipped", "shipment",
]

# Silverbene sends from these domains
_SILVERBENE_SENDERS = ["silverbene.com", "silverbene"]


def _imap_connect():
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_password:
        print("[ShippingMonitor] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set")
        return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, gmail_password)
        return mail
    except Exception as e:
        print(f"[ShippingMonitor] IMAP connect error: {e}")
        return None


def _get_email_text(msg) -> str:
    """Extract plain text + html body from email message."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(part.get_payload(decode=True).decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            parts.append(msg.get_payload(decode=True).decode(charset, errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)


def _extract_tracking_number(text: str) -> tuple:
    """Return (tracking_number, carrier) or (None, None)."""
    for pattern, carrier in _TRACKING_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1), carrier
    return None, None


def _find_matching_order(text: str) -> "OrderTracking | None":
    """
    Find an unshipped OrderTracking record whose cj_order_id appears in the email text.
    Falls back to the most recent unshipped Silverbene order if only one exists.
    """
    with Session(engine) as session:
        pending = session.exec(
            select(OrderTracking).where(
                OrderTracking.supplier_name == "Silverbene",
                OrderTracking.shipping_notified == False,
            )
        ).all()

    if not pending:
        return None

    # Try exact cj_order_id match first
    for t in pending:
        if t.cj_order_id and str(t.cj_order_id) in text:
            print(f"[ShippingMonitor] Matched order {t.order_id} via cj_order_id={t.cj_order_id}")
            return t

    # If there's only one unshipped order, it must be this one
    if len(pending) == 1:
        print(f"[ShippingMonitor] Single unshipped order — assuming order {pending[0].order_id}")
        return pending[0]

    print(f"[ShippingMonitor] {len(pending)} unshipped orders but none matched email text")
    return None


def _is_shipping_email(sender: str, subject: str, body: str) -> bool:
    combined = (sender + " " + subject + " " + body[:500]).lower()
    from_silverbene = any(s in sender.lower() for s in _SILVERBENE_SENDERS)
    has_keyword = any(kw in combined for kw in _SHIPPING_KEYWORDS)
    return from_silverbene and has_keyword


def run_silverbene_shipping_monitor():
    """
    Main entry point — called by the scheduler every 2 hours.
    Scans hello@mikisi.co inbox for Silverbene shipping emails and
    automatically triggers Mikisi customer notifications.
    """
    print(f"\n[ShippingMonitor] Scanning inbox — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    mail = _imap_connect()
    if not mail:
        return

    try:
        mail.select("INBOX")

        # Search for unread emails from silverbene.com
        _, msgs = mail.search(None, '(UNSEEN FROM "silverbene")')
        email_ids = msgs[0].split() if msgs[0] else []

        if not email_ids:
            print("[ShippingMonitor] No unread Silverbene emails")
            mail.logout()
            return

        print(f"[ShippingMonitor] Found {len(email_ids)} unread Silverbene email(s)")

        for eid in email_ids:
            try:
                _, data = mail.fetch(eid, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                # Decode subject
                raw_subject = msg.get("Subject", "")
                decoded = decode_header(raw_subject)[0]
                subject = decoded[0].decode(decoded[1] or "utf-8") if isinstance(decoded[0], bytes) else decoded[0]

                sender = msg.get("From", "")
                body = _get_email_text(msg)

                print(f"[ShippingMonitor] Email: from={sender!r} subject={subject!r}")

                if not _is_shipping_email(sender, subject, body):
                    print("[ShippingMonitor] Not a shipping notification — skipping")
                    # Still mark as read so we don't check it every cycle
                    mail.store(eid, "+FLAGS", "\\Seen")
                    continue

                tracking_number, carrier = _extract_tracking_number(body + " " + subject)
                if not tracking_number:
                    print("[ShippingMonitor] No tracking number found in email")
                    mail.store(eid, "+FLAGS", "\\Seen")
                    continue

                print(f"[ShippingMonitor] Tracking: {tracking_number} via {carrier}")

                tracking = _find_matching_order(body + " " + subject)
                if not tracking:
                    print("[ShippingMonitor] Could not match to an order — skipping customer email")
                    mail.store(eid, "+FLAGS", "\\Seen")
                    continue

                # Update the tracking record
                with Session(engine) as session:
                    t = session.get(OrderTracking, tracking.id)
                    t.tracking_number = tracking_number
                    t.carrier = carrier
                    t.status = "dispatched"
                    t.shipped_at = datetime.utcnow()
                    session.add(t)
                    session.commit()
                    session.refresh(t)
                    tracking = t

                # Send Mikisi-branded customer notification
                if not tracking.shipping_notified and tracking.customer_email:
                    from app.agents.tracking_agent import send_shipping_email
                    sent = send_shipping_email(tracking)
                    if sent:
                        with Session(engine) as session:
                            t = session.get(OrderTracking, tracking.id)
                            t.shipping_notified = True
                            session.add(t)
                            session.commit()

                        # Update Order status
                        with Session(engine) as session:
                            order = session.get(Order, tracking.order_id)
                            if order:
                                order.status = "shipped"
                                order.tracking_number = tracking_number
                                session.add(order)
                                session.commit()

                        print(f"[ShippingMonitor] Customer notified: {tracking.customer_email}")
                    else:
                        print(f"[ShippingMonitor] Failed to send customer email")

                # Stage 2 variant confirmation — mark order as Silverbene-confirmed
                if tracking.cj_order_id:
                    try:
                        from app.agents.order_variant_tracker import confirm_silverbene_shipped
                        confirm_silverbene_shipped(tracking.cj_order_id)
                    except Exception as vce:
                        print(f"[ShippingMonitor] VariantTracker confirm error: {vce}")

                # Mark the Silverbene email as read
                mail.store(eid, "+FLAGS", "\\Seen")

            except Exception as e:
                import traceback
                print(f"[ShippingMonitor] Error processing email {eid}: {e}")
                traceback.print_exc()

    finally:
        try:
            mail.logout()
        except Exception:
            pass
