from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from sqlmodel import Session, select
from app.models.cart import CartItem
from app.models.product import Product
from app.models.order import Order
from app.database import get_session, engine
from app.auth_utils import verify_token
from app.routes.auth import oauth2_scheme
from pydantic import BaseModel
from typing import Optional
import stripe
import os
import json

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

router = APIRouter()


def _send_meta_capi_event(event_name: str, value: float, content_ids: list, email: str = None, event_id: str = None):
    """
    Server-side Meta Conversions API call — complements the browser Pixel
    (docs/index.html) so the event still reaches Meta even when an ad
    blocker or Safari ITP silently drops the client-side one. Shares
    event_id with the matching client-side fbq() call (both use the Stripe
    checkout session id) so Meta deduplicates the two instead of double-
    counting the same purchase. Must never raise — this fires from the
    order-processing path and a Meta API hiccup must never affect a real
    order. No-ops quietly if META_PIXEL_ID/META_CONVERSIONS_API_TOKEN
    aren't set (or the token is still Railway's placeholder text) — a bad
    token just gets a failed request logged below, not a crash.
    """
    pixel_id = os.getenv("META_PIXEL_ID")
    token = os.getenv("META_CONVERSIONS_API_TOKEN")
    if not pixel_id or not token:
        return
    try:
        import requests
        import hashlib
        import time
        user_data = {}
        if email:
            user_data["em"] = [hashlib.sha256(email.strip().lower().encode()).hexdigest()]
        resp = requests.post(
            f"https://graph.facebook.com/v18.0/{pixel_id}/events",
            params={"access_token": token},
            json={"data": [{
                "event_name": event_name,
                "event_time": int(time.time()),
                "action_source": "website",
                "event_id": event_id,
                "user_data": user_data,
                "custom_data": {
                    "value": round(value, 2),
                    "currency": "usd",
                    "content_ids": [str(c) for c in content_ids],
                    "content_type": "product",
                },
            }]},
            timeout=10,
        )
        if not resp.ok:
            print(f"[Meta CAPI] {event_name} rejected: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        print(f"[Meta CAPI] Failed to send {event_name}: {e}")


def _option_id_in_variants(variants_json, option_id) -> bool:
    """Whether option_id actually appears among this product's own variants."""
    try:
        variants = json.loads(variants_json or "[]")
    except Exception:
        return False
    return any(str(v.get("option_id")) == str(option_id) for v in variants)

class CheckoutRequest(BaseModel):
    shipping_address: str
    shipping_method: str = "usps"  # "fast_track" or "usps"

@router.post("/payments/create-checkout")
def create_checkout_session(
    request: CheckoutRequest,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme)
):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_email = payload.get("sub")

    items = session.exec(
        select(CartItem).where(CartItem.user_id == user_email)
    ).all()

    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    line_items = []
    content_ids = []
    order_value = 0.0
    for item in items:
        product = session.get(Product, item.product_id)
        if product:
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{product.brand} - {product.name}",
                        "description": (product.description or "")[:50],
                    },
                    "unit_amount": int(product.final_price * 100),
                },
                "quantity": item.quantity,
            })
            content_ids.append(str(product.id))
            order_value += product.final_price * item.quantity

    frontend_url = "https://deniskleindkm-droid.github.io/api-project"
    # value/currency/content_ids let the success page fire an accurate Meta
    # Pixel Purchase event (see docs/index.html) without a second lookup —
    # the total is already known here, before Stripe redirects the customer
    # away from our own domain.
    # {{CHECKOUT_SESSION_ID}} is Stripe's own literal placeholder syntax --
    # Stripe substitutes it with the real session id before redirecting.
    # The client (docs/index.html) reads it back out to pass as fbq()'s
    # eventID, matching the event_id _send_meta_capi_event() uses server-side
    # for the same Purchase, so Meta dedupes the two instead of double-
    # counting one sale.
    success_params = f"payment=success&value={order_value:.2f}&currency=usd&content_ids={','.join(content_ids)}&session_id={{CHECKOUT_SESSION_ID}}"

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=f"{frontend_url}?{success_params}",
        cancel_url=f"{frontend_url}?payment=cancelled",
        customer_email=user_email,
        metadata={
            "user_email": user_email,
            "shipping_address": request.shipping_address,
            "shipping_method": request.shipping_method,
        }
    )

    return {"checkout_url": checkout_session.url}


class GuestCartItem(BaseModel):
    product_id: int
    quantity: int = 1
    # Optional[...] is required, not just the "= None" default — Pydantic v2
    # validates an explicit JSON `null` against the declared type, and a bare
    # `str`/`int` annotation rejects it even though the default is None. The
    # frontend (docs/index.html, docs/checkout.html) always sends these keys
    # explicitly as `null` when a product has no color/size chip or hasn't
    # been backfilled into ProductVariant yet — found live 2026-07-21: any
    # guest checkout for a product with no selected_color (e.g. a single-
    # finish ring, no color chip at all) got a silent 422 here, which the
    # frontend's placeOrder() displayed as the literal text "[object Object]"
    # (data.detail is FastAPI's validation-error array, not a string) —
    # looked exactly like "Pay Securely" doing nothing no matter how many
    # times it was clicked.
    selected_size: Optional[str] = None
    selected_color: Optional[str] = None
    selected_option_id: Optional[str] = None
    variant_id: Optional[int] = None

class GuestCheckoutRequest(BaseModel):
    items: list[GuestCartItem]
    email: str
    first_name: str
    last_name: str
    shipping_address: str
    shipping_method: str = "usps"


@router.post("/payments/guest-checkout")
def create_guest_checkout_session(
    request: GuestCheckoutRequest,
    session: Session = Depends(get_session),
):
    if not request.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    line_items = []
    items_meta = []
    content_ids = []
    order_value = 0.0
    for item in request.items:
        product = session.get(Product, item.product_id)
        if not product or not product.is_active or not product.is_published:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} is no longer available")
        # Mirrors _require_published_or_preview in routes/products.py — a
        # hidden-category product must never be purchasable even if it
        # somehow ended up in the cart (see the same fix in routes/cart.py's
        # add_to_cart; this is the actual money-taking step, so it gets its
        # own check rather than relying solely on that earlier gate).
        from app.agents.store_config import get_hidden_categories
        if product.category in get_hidden_categories():
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} is no longer available")
        if product.stock == 0:
            raise HTTPException(status_code=400, detail=f"'{product.name[:40]}' is out of stock")
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Mikisi — {product.name[:50]}",
                    "description": (product.description or "")[:50],
                },
                "unit_amount": int(product.final_price * 100),
            },
            "quantity": item.quantity,
        })
        items_meta.append({
            "product_id": product.id,
            "quantity": item.quantity,
            "selected_size": item.selected_size,
            "selected_color": item.selected_color,
            "selected_option_id": item.selected_option_id,
            "variant_id": item.variant_id,
        })
        content_ids.append(str(product.id))
        order_value += product.final_price * item.quantity

    # value/currency/content_ids let the success page fire an accurate Meta
    # Pixel Purchase event (see docs/index.html) without a second lookup —
    # the total is already known here, before Stripe redirects the customer
    # away from our own domain.
    # {{CHECKOUT_SESSION_ID}} is Stripe's own literal placeholder syntax --
    # Stripe substitutes it with the real session id before redirecting.
    # The client (docs/index.html) reads it back out to pass as fbq()'s
    # eventID, matching the event_id _send_meta_capi_event() uses server-side
    # for the same Purchase, so Meta dedupes the two instead of double-
    # counting one sale.
    success_params = f"payment=success&value={order_value:.2f}&currency=usd&content_ids={','.join(content_ids)}&session_id={{CHECKOUT_SESSION_ID}}"

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=f"https://mikisi.co/?{success_params}",
        cancel_url="https://mikisi.co/",
        customer_email=request.email,
        metadata={
            "user_email":       request.email,
            "first_name":       request.first_name,
            "last_name":        request.last_name,
            "shipping_address": request.shipping_address,
            "shipping_method":  request.shipping_method,
            "guest_items":      json.dumps(items_meta),
            "is_guest":         "true",
        },
    )
    return {"checkout_url": checkout_session.url}


def process_order_background(checkout_data: dict):
    try:
        user_email = checkout_data["metadata"]["user_email"]
        shipping_address = checkout_data["metadata"]["shipping_address"]
        shipping_method = checkout_data["metadata"].get("shipping_method", "usps")
        is_guest = checkout_data["metadata"].get("is_guest") == "true"
        first_name = checkout_data["metadata"].get("first_name", "")
        last_name = checkout_data["metadata"].get("last_name", "")
        guest_items_raw = checkout_data["metadata"].get("guest_items", "[]")
        stripe_session_id = checkout_data["metadata"].get("stripe_session_id")

        # Idempotency guard — Stripe explicitly documents that the same webhook
        # event can be delivered more than once, and the admin recover-order
        # endpoint funnels through here too (which could otherwise replay an
        # already-processed session). Without this, a duplicate delivery would
        # re-decrement stock, re-charge Silverbene for the same items, and
        # create duplicate Order rows. Orders placed before this column
        # existed have stripe_session_id=None, so this only guards sessions
        # that actually carry one.
        if stripe_session_id:
            with Session(engine) as _idem_session:
                already = _idem_session.exec(
                    select(Order).where(Order.stripe_session_id == stripe_session_id)
                ).first()
            if already:
                print(f"[Payments] Session {stripe_session_id} already processed (order #{already.id}) — skipping duplicate webhook/recovery delivery")
                return

        order_details = []
        total = 0

        with Session(engine) as session:
            if is_guest:
                guest_items = json.loads(guest_items_raw)
                print(f"[Payments] Guest order — {len(guest_items)} item(s) for {user_email}")
                for item_data in guest_items:
                    product = session.get(Product, item_data["product_id"])
                    qty = item_data.get("quantity", 1)
                    if product:
                        subtotal = product.final_price * qty
                        total += subtotal
                        sel_size  = item_data.get("selected_size")
                        sel_color = item_data.get("selected_color")
                        sel_option_id = item_data.get("selected_option_id")
                        sel_variant_id = item_data.get("variant_id")
                        order_details.append({
                            "name": product.name,
                            "qty": qty,
                            "price": product.final_price,
                            "subtotal": subtotal,
                            "supplier": product.supplier_name,
                            "supplier_url": product.supplier_url,
                            "product_id": product.id,
                            "cj_sku": product.cj_sku,
                            "cj_product_id": product.cj_product_id,
                            "variants": product.variants,
                            "selected_size": sel_size,
                            "selected_color": sel_color,
                            "selected_option_id": sel_option_id,
                            "variant_id": sel_variant_id,
                        })
                        print(f"[Payments] Guest item: {product.name} — size={sel_size} color={sel_color}")
                        order = Order(
                            user_id=user_email,
                            guest_email=user_email,
                            is_guest=True,
                            product_id=product.id,
                            quantity=qty,
                            total_price=subtotal,
                            status="paid",
                            shipping_address=shipping_address,
                            shipping_method=shipping_method,
                            variant_id=sel_variant_id,
                            stripe_session_id=stripe_session_id,
                        )
                        product.stock -= qty
                        session.add(order)
                        session.add(product)
                session.commit()
            else:
                cart_items = session.exec(
                    select(CartItem).where(CartItem.user_id == user_email)
                ).all()

                print(f"[Payments] Found {len(cart_items)} cart items for {user_email}")

                if not cart_items:
                    print(f"[Payments] Cart already empty for {user_email} — webhook retry or already processed. Skipping.")
                    return

                for item in cart_items:
                    product = session.get(Product, item.product_id)
                    if product:
                        subtotal = product.final_price * item.quantity
                        total += subtotal
                        order_details.append({
                            "name": product.name,
                            "qty": item.quantity,
                            "price": product.final_price,
                            "subtotal": subtotal,
                            "supplier": product.supplier_name,
                            "supplier_url": product.supplier_url,
                            "product_id": item.product_id,
                            "cj_sku": product.cj_sku,
                            "cj_product_id": product.cj_product_id,
                            "variants": product.variants,
                            "selected_size": item.selected_size,
                            "selected_color": item.selected_color,
                            "selected_option_id": item.selected_option_id,
                            "variant_id": item.variant_id,
                        })
                        print(f"[Payments] Item: {product.name} — size={item.selected_size} color={item.selected_color}")
                        order = Order(
                            user_id=user_email,
                            product_id=item.product_id,
                            quantity=item.quantity,
                            total_price=subtotal,
                            status="paid",
                            shipping_address=shipping_address,
                            shipping_method=shipping_method,
                            variant_id=item.variant_id,
                            stripe_session_id=stripe_session_id,
                        )
                        product.stock -= item.quantity
                        session.add(order)
                        session.add(product)
                        session.delete(item)

                session.commit()

        print(f"[Payments] Order details collected: {len(order_details)} items, total ${total:.2f}")

        # event_id = stripe_session_id, shared with the client-side fbq()
        # Purchase call fired from the same checkout session's success_url
        # (see docs/index.html) — Meta dedupes on event_id, so this must
        # never fire without a real session id, or a webhook retry replaying
        # a duplicate id would double-count real revenue.
        if stripe_session_id:
            _send_meta_capi_event(
                "Purchase", total,
                [d["product_id"] for d in order_details],
                email=user_email,
                event_id=stripe_session_id,
            )

        # Auto-forward to Silverbene
        try:
            from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter, resolve_option_id
            from app.agents.tracking_agent import create_tracking_entry
            from app.agents.order_variant_tracker import check_order_item, send_batched_order_alert
            silverbene = SilverbeneAdapter()
            _variant_problems: list = []

            print(f"[Payments] Starting Silverbene forwarding for {len(order_details)} items")

            if first_name:
                customer_first = first_name.capitalize()
                customer_last  = last_name.capitalize() if last_name else "Customer"
            else:
                customer_name_parts = user_email.split("@")[0].split(".")
                customer_first = customer_name_parts[0].capitalize()
                customer_last  = customer_name_parts[1].capitalize() if len(customer_name_parts) > 1 else "Customer"

            # Parse shipping_address string into structured fields
            # Expected format: "123 Street, City, State, ZIP, Country"
            def _parse_address(addr_str: str) -> dict:
                parts = [p.strip() for p in addr_str.split(",")]
                return {
                    "line1":        parts[0] if len(parts) > 0 else "",
                    "city":         parts[1] if len(parts) > 1 else "",
                    "state":        parts[2] if len(parts) > 2 else "",
                    "state_code":   parts[2][:2].upper() if len(parts) > 2 else "",
                    "postal_code":  parts[3].strip() if len(parts) > 3 else "",
                    "country_code": parts[4].strip().upper() if len(parts) > 4 else "US",
                }

            address = _parse_address(shipping_address)

            customer = {
                "first_name": customer_first,
                "last_name":  customer_last,
                "email":      "hello@mikisi.co",  # never send real customer email to supplier
                "phone":      "",
            }

            # Get saved orders for tracking linkage
            with Session(engine) as session:
                saved_orders = session.exec(
                    select(Order).where(
                        Order.user_id == user_email,
                        Order.status == "paid"
                    ).order_by(Order.id.desc()).limit(len(order_details))
                ).all()

            # Pre-flight: check Silverbene balance before placing any orders.
            # If balance is critically low (<$20), hold all orders as pending_credit
            # rather than letting Silverbene send payment requests.
            sb_balance = silverbene.check_balance()
            balance_ok = sb_balance < 0 or sb_balance >= 20  # -1 means API unavailable → proceed
            if sb_balance >= 0 and sb_balance < 50:
                # Warn Dennis proactively (not critical yet, but worth knowing)
                silverbene._alert_low_credit(
                    subject=f"⚠️ Silverbene balance low: ${sb_balance:.2f}",
                    body=(
                        f"<p>Your Silverbene store credit is <b>${sb_balance:.2f}</b>. "
                        f"Top up now to avoid order failures.</p>"
                        f"<p>Contact Jacky: <a href='mailto:jackyli@silverbene.com'>jackyli@silverbene.com</a> "
                        f"or WhatsApp +86 180 2239 4913</p>"
                    ),
                )
            print(f"[Payments] Silverbene balance: {'${:.2f}'.format(sb_balance) if sb_balance >= 0 else 'unknown'} — proceed={balance_ok}")

            for i, d in enumerate(order_details):
                # The internal variant_id (the ProductVariant primary key) is the
                # primary field going forward — resolved once by the frontend when
                # the customer made their selection, carried straight through cart
                # and checkout. Trust it directly, but never blindly: a client-
                # submitted variant_id that doesn't actually belong to THIS product
                # (spoofed, stale, or from a mismatched deep link) would place a
                # real Silverbene order for the wrong item, so it's checked against
                # the product before its supplier_option_id is ever used. This is
                # the one point both the guest and logged-in checkout paths funnel
                # through before the real supplier order call, so it's the
                # last-chance gate to catch that before money moves.
                option_id = None
                resolve_pass = None
                variant_id = d.get("variant_id")
                if variant_id:
                    from app.models.product_variant import ProductVariant
                    with Session(engine) as vsession:
                        variant = vsession.get(ProductVariant, variant_id)
                    if variant and variant.product_id == d.get("product_id"):
                        option_id, resolve_pass = variant.supplier_option_id, "variant_id"
                    else:
                        print(f"[Payments] variant_id={variant_id} does not belong to product {d.get('product_id')} — ignoring, falling back")

                # Legacy fallback (older/direct-API clients that never sent a
                # variant_id, or a straddling deploy where the browser tab loaded
                # before this field existed) — same option_id/selected_option_id
                # text-resolution path this always used, kept only until traffic
                # on it is confirmed at zero (see [[refactored-wobbling-rabin]]).
                if option_id is None:
                    option_id_from_cart = d.get("selected_option_id")
                    if option_id_from_cart and not _option_id_in_variants(d.get("variants"), option_id_from_cart):
                        print(f"[Payments] selected_option_id={option_id_from_cart} does not belong to product {d.get('product_id')} — ignoring, re-resolving from size/color")
                        option_id_from_cart = None
                    if option_id_from_cart:
                        option_id, resolve_pass = option_id_from_cart, "client_selected"
                    else:
                        resolved, resolve_pass = resolve_option_id(
                            d.get("variants"),
                            d.get("selected_size"),
                            d.get("selected_color"),
                            return_meta=True,
                        ) or (None, "not_found")
                        option_id = resolved or d.get("cj_sku")   # fallback: first variant
                sku       = d.get("cj_product_id")
                db_order_id = saved_orders[i].id if saved_orders and i < len(saved_orders) else (saved_orders[0].id if saved_orders else None)
                print(f"[Payments] Forwarding to Silverbene: {d['name']} | size={d.get('selected_size')} color={d.get('selected_color')} | option_id={option_id}")

                if not option_id:
                    print(f"[Payments] No Silverbene option_id for {d['name']} — manual fulfillment needed")
                    continue

                # If balance is critically low, hold order instead of risking a Silverbene payment request
                if not balance_ok and db_order_id:
                    with Session(engine) as session:
                        order_rec = session.get(Order, db_order_id)
                        if order_rec:
                            order_rec.status = "pending_credit"
                            session.add(order_rec)
                            session.commit()
                    silverbene._alert_low_credit(
                        subject=f"❌ Order #{db_order_id} held — Silverbene balance too low (${sb_balance:.2f})",
                        body=(
                            f"<p>Order <b>#{db_order_id}</b> for <b>{d['name']}</b> could not be sent to Silverbene "
                            f"because your store credit is <b>${sb_balance:.2f}</b> — below the $20 safety threshold.</p>"
                            f"<p>The customer has been charged and will receive a confirmation email from Mikisi. "
                            f"The order will be retried automatically every 2 hours once your balance is topped up.</p>"
                            f"<p><b>Top up now:</b> Contact Jacky at "
                            f"<a href='mailto:jackyli@silverbene.com'>jackyli@silverbene.com</a></p>"
                        ),
                    )
                    print(f"[Payments] Order #{db_order_id} held as pending_credit — balance ${sb_balance:.2f}")
                    continue

                result = silverbene.place_order(
                    product_id=str(option_id),
                    customer=customer,
                    address=address,
                    quantity=d["qty"],
                    option_id=str(option_id),
                )
                print(f"[Payments] Silverbene order result: {result}")

                if result.get("success") and db_order_id:
                    silverbene_order_id = result.get("supplier_order_id", "")
                    create_tracking_entry(
                        order_id=db_order_id,
                        cj_order_id=silverbene_order_id,
                        customer_email=user_email,
                        customer_name=f"{customer_first} {customer_last}",
                        supplier_name="Silverbene"
                    )
                    with Session(engine) as session:
                        order_rec = session.get(Order, db_order_id)
                        if order_rec:
                            order_rec.status = "processing"
                            order_rec.supplier_notified = True
                            session.add(order_rec)
                            session.commit()

                    # Variant tracker — Stage 1: verify size/color routing is correct
                    # send_alert=False: payments.py sends ONE batched email after the loop
                    try:
                        vc_record = check_order_item(
                            order_id=db_order_id,
                            silverbene_order_id=silverbene_order_id,
                            product_id=d.get("product_id", 0),
                            product_name=d["name"],
                            variants_json=d.get("variants") or "",
                            option_id_sent=str(option_id),
                            resolve_pass=resolve_pass or "unknown",
                            selected_size=d.get("selected_size") or "",
                            selected_color=d.get("selected_color") or "",
                            customer_email=user_email,
                            customer_name=f"{customer_first} {customer_last}",
                            send_alert=False,
                        )
                        if vc_record.match_status not in ("ok", "no_variants"):
                            _variant_problems.append(vc_record)
                    except Exception as ve:
                        print(f"[Payments] VariantTracker error (non-fatal): {ve}")

                elif not result.get("success"):
                    reason = result.get("reason", "unknown error")
                    print(f"[Payments] Silverbene rejected order for {d['name']}: {reason}")
                    if "insufficient_credit" in reason and db_order_id:
                        with Session(engine) as session:
                            order_rec = session.get(Order, db_order_id)
                            if order_rec:
                                order_rec.status = "pending_credit"
                                session.add(order_rec)
                                session.commit()
                    else:
                        # Any other rejection reason (stock issue, invalid address,
                        # API error, etc.) previously had NO immediate alert — the
                        # customer was already charged, but Dennis had zero
                        # visibility until order_recovery_agent.py's 2-hour-stuck
                        # sweep, a silent window during which the order simply sat
                        # unforwarded. supplier_notified stays False either way, so
                        # the automatic 30-minute retry sweep still picks this order
                        # up and will self-heal it without any further action —
                        # this alert is purely about closing the visibility gap,
                        # not a substitute for that retry.
                        silverbene._alert_low_credit(
                            subject=f"⚠️ Order #{db_order_id or '?'} — Silverbene rejected: {reason}",
                            body=(
                                f"<p>Order <b>#{db_order_id or '?'}</b> for <b>{d['name']}</b> "
                                f"was rejected by Silverbene.</p>"
                                f"<p><b>Reason:</b> {reason}</p>"
                                f"<p>The customer has already been charged. The automatic recovery "
                                f"agent will keep retrying this order every 30 minutes — no action "
                                f"needed unless it's still failing in a couple of hours.</p>"
                            ),
                        )

            # One batched alert per order if anything was mismatched
            if _variant_problems and saved_orders:
                send_batched_order_alert(saved_orders[0].id, _variant_problems)

        except Exception as e:
            print(f"[Payments] Silverbene forwarding failed: {e}")

        # Build items HTML for emails
        items_html = "".join([
            f"<tr><td>{d['name']}</td><td>{d['qty']}</td><td>${d['price']:.2f}</td><td>${d['subtotal']:.2f}</td></tr>"
            for d in order_details
        ])

        items_html_customer = "".join([
            f"<tr><td style='padding:10px 0;font-size:14px;font-weight:300;color:#0e0e0e;border-bottom:1px solid #ece5dd;'>{d['name']}</td><td style='text-align:center;padding:10px 0;font-size:14px;font-weight:300;color:#6b6b6b;border-bottom:1px solid #ece5dd;'>{d['qty']}</td><td style='text-align:right;padding:10px 0;font-family:Georgia,serif;font-size:16px;color:#0e0e0e;border-bottom:1px solid #ece5dd;'>${d['subtotal']:.2f}</td></tr>"
            for d in order_details
        ])

        # Send email notification to Dennis
        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL")

            send_email(
                to=dennis_email,
                subject=f"New Mikisi Order — ${total:.2f}",
                body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#d4849c;">New Order Received!</h2>
<p><strong>Customer:</strong> {user_email}</p>
<p><strong>Shipping Address:</strong> {shipping_address}</p>
<h3>Order Details:</h3>
<table border="1" cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;">
<tr style="background:#f5f5f5;">
    <th>Product</th><th>Qty</th><th>Price</th><th>Subtotal</th>
</tr>
{items_html}
<tr style="background:#fff5f7;">
    <td colspan="3"><strong>Total</strong></td>
    <td><strong>${total:.2f}</strong></td>
</tr>
</table>
<br>
<p style="color:#d4849c;font-weight:bold;">Silverbene order forwarding attempted automatically.</p>
<p>Ship to: {shipping_address}</p>
</body></html>""",
                is_html=True
            )
            print(f"[Payments] Order notification sent to Dennis — ${total:.2f}")
        except Exception as e:
            print(f"[Payments] Dennis email failed: {e}")

        # Send confirmation email to customer
        try:
            from app.agents.email_partner import send_email
            send_email(
                to=user_email,
                subject="Your Mikisi Order is Confirmed ✨",
                body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#fdf9f6;">
<div style="text-align:center;padding:32px 0;">
    <h1 style="font-family:Georgia,serif;color:#0e0e0e;letter-spacing:4px;text-transform:uppercase;font-size:28px;font-weight:300;">Mik<em style="color:#d4849c;">i</em>si</h1>
    <p style="font-size:11px;color:#888;letter-spacing:3px;text-transform:uppercase;">Look Elegant and Polished</p>
</div>
<div style="background:white;padding:32px;border:1px solid #ece5dd;">
    <h2 style="font-family:Georgia,serif;font-weight:300;font-size:24px;color:#0e0e0e;margin-bottom:8px;">Your order is confirmed.</h2>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">Thank you for your purchase. We're preparing your order and it will be on its way soon.</p>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:16px;">Order Summary</h3>
    <table style="width:100%;border-collapse:collapse;">
        <tr style="border-bottom:1px solid #ece5dd;">
            <th style="text-align:left;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Product</th>
            <th style="text-align:center;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Qty</th>
            <th style="text-align:right;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Price</th>
        </tr>
        {items_html_customer}
        <tr>
            <td colspan="2" style="padding:16px 0 8px;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#888;">Total</td>
            <td style="padding:16px 0 8px;text-align:right;font-family:Georgia,serif;font-size:20px;color:#0e0e0e;">${total:.2f}</td>
        </tr>
    </table>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:12px;">Shipping To</h3>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">{shipping_address}</p>
    <p style="color:#6b6b6b;font-size:13px;font-weight:300;margin-top:16px;">Estimated delivery: 8–10 business days via USPS</p>
</div>
<div style="text-align:center;padding:32px 0;">
    <p style="font-size:11px;color:#bbb;letter-spacing:1px;">Questions? Contact us at hello@mikisi.co</p>
    <p style="font-size:10px;color:#ccc;margin-top:8px;letter-spacing:1px;">© 2026 Mikisi · Look Elegant and Polished</p>
</div>
</body></html>""",
                is_html=True
            )
            print(f"[Payments] Customer confirmation sent to {user_email}")
        except Exception as e:
            print(f"[Payments] Customer email failed: {e}")

    except Exception as e:
        print(f"[Payments] Background processing failed: {e}")


def _stripe_meta(obj, key: str, default: str = "") -> str:
    try:
        return obj[key]
    except (KeyError, TypeError):
        return default


@router.post("/payments/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            print("[Payments] WARNING: STRIPE_WEBHOOK_SECRET not set — skipping signature verification")
            event = json.loads(payload)
    except stripe.error.SignatureVerificationError as e:
        print(f"[Payments] Webhook signature mismatch — check STRIPE_WEBHOOK_SECRET in Railway: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"[Payments] Webhook parse error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        raw = getattr(obj, "metadata", None) or {}
        metadata = {
            "user_email":       _stripe_meta(raw, "user_email"),
            "shipping_address": _stripe_meta(raw, "shipping_address"),
            "shipping_method":  _stripe_meta(raw, "shipping_method", "usps"),
            "is_guest":         _stripe_meta(raw, "is_guest"),
            "guest_items":      _stripe_meta(raw, "guest_items"),
            "first_name":       _stripe_meta(raw, "first_name"),
            "last_name":        _stripe_meta(raw, "last_name"),
            # Idempotency key — Stripe explicitly documents that the same
            # webhook event can be delivered more than once (retries on
            # timeout/non-2xx, or plain duplicate delivery). Checked in
            # process_order_background() before any Order is created, so a
            # duplicate delivery can never double-charge Silverbene or
            # double-decrement stock.
            "stripe_session_id": getattr(obj, "id", None),
        }
        background_tasks.add_task(process_order_background, {"metadata": metadata})

    return {"status": "ok"}


@router.post("/payments/recover-order/{session_id}")
async def recover_missed_order(
    session_id: str,
    background_tasks: BackgroundTasks,
    master_key: str = "",
    token: str = Depends(oauth2_scheme)
):
    """
    Admin endpoint: manually replay a Stripe checkout session that the webhook missed.
    Use this when a customer paid but the order wasn't recorded.
    """
    from app.agents.aria_security import verify_master_key
    payload = verify_token(token)
    if not payload and not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        checkout_obj = stripe.checkout.Session.retrieve(session_id)
        if getattr(checkout_obj, "payment_status", None) != "paid":
            raise HTTPException(status_code=400, detail="Session not paid yet")
        raw = getattr(checkout_obj, "metadata", None) or {}
        # Previously never read is_guest/guest_items — a guest checkout's
        # session has NO CartItem rows to build order_details from (guest
        # order_details come entirely from guest_items metadata), so replaying
        # a missed guest session silently took the logged-in path, found an
        # empty cart, and did nothing at all — this endpoint simply never
        # worked for a guest's missed order. stripe_session_id is the same
        # idempotency key process_order_background() checks for the webhook
        # path, so replaying an already-processed session here is also a safe
        # no-op instead of a duplicate order.
        metadata = {
            "user_email":       _stripe_meta(raw, "user_email"),
            "shipping_address": _stripe_meta(raw, "shipping_address"),
            "shipping_method":  _stripe_meta(raw, "shipping_method", "usps"),
            "is_guest":         _stripe_meta(raw, "is_guest"),
            "guest_items":      _stripe_meta(raw, "guest_items"),
            "first_name":       _stripe_meta(raw, "first_name"),
            "last_name":        _stripe_meta(raw, "last_name"),
            "stripe_session_id": session_id,
        }
        background_tasks.add_task(process_order_background, {"metadata": metadata})
        return {"status": "recovery_started", "session_id": session_id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))