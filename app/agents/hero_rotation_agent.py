"""
Hero Rotation Agent
-------------------
Keeps the homepage hero rotation stocked with real, currently-live product
photos instead of a fixed, manually-picked set — products come and go
(discontinued, unpublished, out of stock), so a hand-picked permanent set
would eventually go stale or point at something no longer for sale.

Every run: picks the 2 strongest published + in-stock photos from each of
5 categories (Rings, Necklaces, Bracelets, Earrings, Anklets — Ear Cuffs
excluded per Dennis) and re-hosts them onto 10 fixed Cloudinary slots. A
product that stops qualifying (discontinued, unpublished, sells out) simply
isn't picked next refresh — no dangling reference, no manual cleanup.

"Quality" ranks on signals every product row actually has (is_premium,
final_price, gallery size) rather than ProductScore, which only covers a
sparse ~13% of the active catalog (import-time scoring, not universal).
"""
import json
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product

HERO_CATEGORIES = ["Rings", "Necklaces", "Bracelets", "Earrings", "Anklets"]
PICKS_PER_CATEGORY = 2


def _quality_key(p: Product):
    try:
        n_images = len(json.loads(p.images or "[]"))
    except Exception:
        n_images = 0
    return (1 if p.is_premium else 0, p.final_price or 0.0, n_images)


def _pick_best_per_category(session: Session, category: str, limit: int) -> list:
    candidates = session.exec(
        select(Product).where(
            Product.category == category,
            Product.is_active == True,
            Product.is_published == True,
            Product.stock > 0,
            Product.image_url != None,
        )
    ).all()
    candidates.sort(key=_quality_key, reverse=True)
    return candidates[:limit]


def run_hero_rotation_refresh():
    from app.agents.cloudinary_agent import store_hero_rotation_image
    from app.agents.store_config import set_config

    picks = []
    with Session(engine) as session:
        for category in HERO_CATEGORIES:
            for p in _pick_best_per_category(session, category, PICKS_PER_CATEGORY):
                picks.append((category, p))

    rotation = []
    for slot, (category, p) in enumerate(picks):
        source = p.content_image_url or p.image_url
        if not source:
            continue
        cdn_url = store_hero_rotation_image(slot, source)
        if cdn_url:
            rotation.append({"url": cdn_url, "category": category, "product_id": p.id})

    if not rotation:
        print("[Hero Rotation] No eligible products found — leaving existing rotation untouched")
        return

    set_config("hero_rotation", json.dumps(rotation),
                "Rotating hero images — 2 per category (no Ear Cuffs), refreshed every 2 days")
    set_config("hero_rotation_updated_at", datetime.utcnow().isoformat(), "Last hero rotation refresh")
    print(f"[Hero Rotation] Refreshed {len(rotation)} images across {len(HERO_CATEGORIES)} categories")
