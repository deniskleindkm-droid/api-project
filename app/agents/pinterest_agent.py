"""
Pinterest Agent — Mikisi

Handles:
  1. Board creation (one per collection, run once)
  2. Product catalog sync (add / update / out-of-stock)
  3. Product pin creation with ARIA-generated descriptions
  4. Daily analytics pull

All operations are non-blocking and fail gracefully — a Pinterest error
never crashes the import pipeline.
"""
import os
import json
import re
from datetime import datetime, timedelta

import requests

PINTEREST_API  = "https://api.pinterest.com/v5"
MIKISI_URL     = "https://mikisi.co"

BOARD_CONFIGS = {
    "Necklaces": {
        "name": "Mikisi Necklaces",
        "description": (
            "Exquisite sterling silver necklaces crafted for the woman "
            "who wears her story. Shop at mikisi.co"
        ),
    },
    "Earrings": {
        "name": "Mikisi Earrings",
        "description": (
            "Fine sterling silver earrings — from delicate studs to "
            "statement hoops. Shop at mikisi.co"
        ),
    },
    "Rings": {
        "name": "Mikisi Rings",
        "description": (
            "Sterling silver rings for every moment that deserves to "
            "be marked. Shop at mikisi.co"
        ),
    },
    "Bracelets": {
        "name": "Mikisi Bracelets",
        "description": (
            "Elegant silver bracelets and bangles that adorn every "
            "wrist beautifully. Shop at mikisi.co"
        ),
    },
    "Anklets": {
        "name": "Mikisi Anklets",
        "description": (
            "Delicate sterling silver anklets — grace in every step. "
            "Shop at mikisi.co"
        ),
    },
    "Ear Cuffs": {
        "name": "Mikisi Ear Cuffs",
        "description": (
            "No piercing required. Sterling silver ear cuffs for "
            "effortless elegance. Shop at mikisi.co"
        ),
    },
}


# ── HTTP HELPERS ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = os.getenv("PINTEREST_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, params: dict = None) -> dict:
    try:
        r = requests.get(
            f"{PINTEREST_API}{endpoint}", headers=_headers(),
            params=params, timeout=15
        )
        return r.json()
    except Exception as e:
        print(f"[Pinterest] GET {endpoint} error: {e}")
        return {}


def _post(endpoint: str, data: dict) -> dict:
    try:
        r = requests.post(
            f"{PINTEREST_API}{endpoint}", headers=_headers(),
            json=data, timeout=15
        )
        return r.json()
    except Exception as e:
        print(f"[Pinterest] POST {endpoint} error: {e}")
        return {}


def _patch(endpoint: str, data: dict) -> dict:
    try:
        r = requests.patch(
            f"{PINTEREST_API}{endpoint}", headers=_headers(),
            json=data, timeout=15
        )
        return r.json()
    except Exception as e:
        print(f"[Pinterest] PATCH {endpoint} error: {e}")
        return {}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


# ── BOARDS ────────────────────────────────────────────────────────────────────

def ensure_boards_exist() -> dict:
    """
    Create the 6 Mikisi Pinterest boards if they don't already exist.
    Saves each board_id to store_config AND the collections table.
    Returns {collection_name: board_id}.
    Safe to call multiple times — skips already-created boards.
    """
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.collection import Collection
    from app.agents.store_config import get_config, set_config

    board_ids = {}

    for collection_name, cfg in BOARD_CONFIGS.items():
        config_key = f"pinterest_board_{collection_name.lower().replace(' ', '_')}"
        existing = get_config(config_key)
        if existing:
            board_ids[collection_name] = existing
            print(f"[Pinterest] Board already exists — {collection_name}: {existing}")
            continue

        resp = _post("/boards", {
            "name": cfg["name"],
            "description": cfg["description"],
            "privacy": "PUBLIC",
        })
        board_id = resp.get("id", "")
        if not board_id:
            print(f"[Pinterest] Board creation failed for {collection_name}: {resp}")
            continue

        set_config(config_key, board_id, f"Pinterest board ID for {collection_name}")
        board_ids[collection_name] = board_id

        with Session(engine) as session:
            col = session.exec(
                select(Collection).where(Collection.name == collection_name)
            ).first()
            if col:
                col.pinterest_board_id = board_id
                session.add(col)
                session.commit()

        print(f"[Pinterest] Board created — {collection_name}: {board_id}")

    return board_ids


def _get_board_id(category: str) -> str:
    """Return board_id for a product category, creating boards if needed."""
    from app.agents.store_config import get_config
    key = f"pinterest_board_{category.lower().replace(' ', '_')}"
    board_id = get_config(key, default="")
    if not board_id:
        board_ids = ensure_boards_exist()
        board_id = board_ids.get(category, "")
    return board_id


# ── CATALOG ───────────────────────────────────────────────────────────────────

def _get_or_create_catalog() -> str:
    """Return the Mikisi Pinterest catalog ID, creating one if it doesn't exist."""
    from app.agents.store_config import get_config, set_config

    catalog_id = get_config("pinterest_catalog_id", default="")
    if catalog_id:
        return catalog_id

    resp = _get("/catalogs")
    for item in resp.get("items", []):
        cid = item.get("id", "")
        if cid:
            set_config("pinterest_catalog_id", cid, "Pinterest catalog ID")
            return cid

    resp = _post("/catalogs", {"name": "Mikisi Products", "catalog_type": "RETAIL"})
    catalog_id = resp.get("id", "")
    if catalog_id:
        set_config("pinterest_catalog_id", catalog_id, "Pinterest catalog ID")
        print(f"[Pinterest] Catalog created: {catalog_id}")

    return catalog_id


def sync_product_to_catalog(product, operation: str = "CREATE") -> bool:
    """
    Add, update, or remove a product from the Pinterest catalog.
    operation: CREATE | UPDATE | DELETE
    """
    catalog_id = _get_or_create_catalog()
    if not catalog_id:
        print(f"[Pinterest] No catalog — cannot sync {product.name}")
        return False

    image_url = product.content_image_url or product.image_url or ""
    if not image_url and operation != "DELETE":
        print(f"[Pinterest] No image for {product.name} — skipping catalog sync")
        return False

    availability = "in stock" if (product.stock or 0) > 0 else "out of stock"

    if operation == "DELETE":
        item = {"item_id": str(product.id), "operation": "DELETE"}
    elif operation == "UPDATE":
        item = {
            "item_id": str(product.id),
            "operation": "UPDATE",
            "attributes": {
                "price": f"{product.final_price:.2f}",
                "currency": "USD",
                "availability": availability,
                "image_link": image_url,
            },
        }
    else:
        description = _strip_html(product.description or "")[:500]
        item = {
            "item_id": str(product.id),
            "operation": "CREATE",
            "attributes": {
                "title": product.name[:150],
                "description": description,
                "link": MIKISI_URL,
                "image_link": image_url,
                "price": f"{product.final_price:.2f}",
                "currency": "USD",
                "availability": availability,
                "condition": "new",
                "google_product_category": "Jewelry",
                "brand": "Mikisi",
            },
        }

    resp = _post(f"/catalogs/items/batch?catalog_id={catalog_id}", {
        "country": "US",
        "language": "EN",
        "operation": operation,
        "items": [item],
    })

    batch_id = resp.get("batch_id", "")
    if batch_id:
        print(f"[Pinterest] Catalog {operation} queued for {product.name}: {batch_id}")
        if operation != "DELETE":
            from sqlmodel import Session
            from app.database import engine
            from app.models.product import Product
            with Session(engine) as session:
                p = session.get(Product, product.id)
                if p:
                    p.pinterest_catalog_id = batch_id
                    p.pinterest_synced_at = datetime.utcnow()
                    session.add(p)
                    session.commit()
        return True

    print(f"[Pinterest] Catalog {operation} failed for {product.name}: {resp}")
    return False


def update_product_availability(product_id: int, available: bool):
    """Called by the stock sync when a product goes in/out of stock."""
    catalog_id = _get_or_create_catalog()
    if not catalog_id:
        return
    availability = "in stock" if available else "out of stock"
    resp = _post(f"/catalogs/items/batch?catalog_id={catalog_id}", {
        "country": "US",
        "language": "EN",
        "operation": "UPDATE",
        "items": [{"item_id": str(product_id), "attributes": {"availability": availability}}],
    })
    if resp.get("batch_id"):
        print(f"[Pinterest] Availability → {availability} for product {product_id}")


# ── PINS ──────────────────────────────────────────────────────────────────────

def generate_pin_description(product) -> str:
    """
    ARIA generates an SEO-optimised Pinterest description.
    2-3 elegant sentences, keywords, ends with 'Shop at mikisi.co'.
    Falls back to a template if Claude is unavailable.
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        material = product.material or "925 sterling silver"
        brief = _strip_html(product.description or "")[:200]

        prompt = (
            f"Write a Pinterest product description for Mikisi luxury jewelry.\n\n"
            f"Product: {product.name}\n"
            f"Material: {material}\n"
            f"Category: {product.category}\n"
            f"Brief: {brief}\n\n"
            f"Rules:\n"
            f"- 2–3 elegant, empowering sentences\n"
            f"- Mention the material naturally\n"
            f"- Include an occasion keyword (gift / everyday / bridal / special occasion)\n"
            f"- Include the category keyword naturally\n"
            f"- Tone: intimate and elegant — never salesy\n"
            f"- End the last sentence with: Shop at mikisi.co\n"
            f"- 500 characters maximum total\n"
            f"- Return ONLY the description text, no labels or quotes"
        )

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if "mikisi.co" not in text:
            text = text.rstrip(".") + ". Shop at mikisi.co"
        return text[:500]

    except Exception as e:
        print(f"[Pinterest] Description generation error: {e}")
        material = product.material or "925 sterling silver"
        return (
            f"A beautiful {product.name.lower()} crafted in {material} — "
            f"perfect for everyday elegance or as a meaningful gift. "
            f"Shop at mikisi.co"
        )[:500]


def create_product_pin(product) -> str:
    """
    Create a Pinterest Product Pin on the correct collection board.
    Returns pin_id on success, empty string on failure.
    """
    board_id = _get_board_id(product.category)
    if not board_id:
        print(f"[Pinterest] No board for '{product.category}' — skipping pin")
        return ""

    image_url = product.content_image_url or product.image_url or ""
    if not image_url:
        print(f"[Pinterest] No image for {product.name} — skipping pin")
        return ""

    description = generate_pin_description(product)

    resp = _post("/pins", {
        "board_id": board_id,
        "title": product.name[:100],
        "description": description,
        "link": MIKISI_URL,
        "media_source": {"source_type": "image_url", "url": image_url},
    })

    pin_id = resp.get("id", "")
    if pin_id:
        from sqlmodel import Session
        from app.database import engine
        from app.models.product import Product
        with Session(engine) as session:
            p = session.get(Product, product.id)
            if p:
                p.pinterest_pin_id = pin_id
                p.pinterest_synced_at = datetime.utcnow()
                session.add(p)
                session.commit()
        print(f"[Pinterest] Pin created for {product.name}: {pin_id}")
    else:
        print(f"[Pinterest] Pin creation failed for {product.name}: {resp}")

    return pin_id


# ── FULL SYNC PIPELINE ────────────────────────────────────────────────────────

def sync_product(product) -> dict:
    """
    Full Pinterest pipeline for one product:
      1. Sync to catalog
      2. Create product pin (description generated inside)
    Returns status dict. Never raises — all errors are caught and logged.
    """
    result = {"product_id": product.id, "catalog": False, "pin_id": ""}

    try:
        result["catalog"] = sync_product_to_catalog(product)
    except Exception as e:
        print(f"[Pinterest] Catalog sync error for {product.name}: {e}")

    try:
        result["pin_id"] = create_product_pin(product)
    except Exception as e:
        print(f"[Pinterest] Pin creation error for {product.name}: {e}")

    # Log to AgentMemory
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="pinterest_agent",
                memory_type="product_sync",
                content=json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "product_id": product.id,
                    "product_name": product.name,
                    "catalog_synced": result["catalog"],
                    "pin_id": result["pin_id"],
                }),
                confidence=0.9,
            ))
            session.commit()
    except Exception as e:
        print(f"[Pinterest] Memory log error: {e}")

    return result


# ── ANALYTICS ─────────────────────────────────────────────────────────────────

def pull_analytics() -> dict:
    """
    Daily: fetch pin metrics for every product that has a pinterest_pin_id.
    Stores results in PlatformAnalytics table.
    """
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.product import Product
    from app.models.platform_analytics import PlatformAnalytics

    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    with Session(engine) as session:
        pinned = session.exec(
            select(Product).where(
                Product.pinterest_pin_id != None,
                Product.is_active == True,
            )
        ).all()

    if not pinned:
        print("[Pinterest] No pinned products yet — skipping analytics pull")
        return {"date": today, "pins_synced": 0}

    synced = 0
    for product in pinned:
        try:
            resp = _get(f"/pins/{product.pinterest_pin_id}/analytics", {
                "start_date": yesterday,
                "end_date": today,
                "metric_types": "IMPRESSION,OUTBOUND_CLICK,PIN_CLICK,SAVE",
                "app_types": "ALL",
            })

            daily = (resp.get("all") or {}).get("daily_metrics") or []
            metrics = (daily[0] if daily else {}).get("metrics", {})

            impressions     = int(metrics.get("IMPRESSION", 0))
            saves           = int(metrics.get("SAVE", 0))
            clicks          = int(metrics.get("PIN_CLICK", 0))
            outbound_clicks = int(metrics.get("OUTBOUND_CLICK", 0))
            engagement      = (
                round((saves + clicks + outbound_clicks) / impressions, 4)
                if impressions > 0 else 0.0
            )

            with Session(engine) as session:
                session.add(PlatformAnalytics(
                    platform="pinterest",
                    post_id=product.pinterest_pin_id,
                    product_id=product.id,
                    date=today,
                    impressions=impressions,
                    saves=saves,
                    clicks=clicks,
                    outbound_clicks=outbound_clicks,
                    engagement_rate=engagement,
                    raw_data=json.dumps(resp)[:2000],
                ))
                session.commit()
            synced += 1

        except Exception as e:
            print(f"[Pinterest] Analytics error for pin {product.pinterest_pin_id}: {e}")

    print(f"[Pinterest] Analytics pulled: {synced}/{len(pinned)} pins on {today}")
    return {"date": today, "pins_synced": synced, "total_pinned": len(pinned)}
