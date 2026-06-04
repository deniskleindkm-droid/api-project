"""
Mikisi Content Agent — orchestrates the full media pipeline.

Pipeline per product:
  1. Generate clean shot       (fal.ai)
  2. Generate lifestyle image  (fal.ai, skin tone rotated)
  3. Upload both to Cloudinary
  4. Save Cloudinary URLs to product record
  5. If in top-20: generate video (Runway) from lifestyle image
  6. Upload video to Cloudinary, save URL

Collection tiles: one video per collection (Runway).
Hero banner: one video (Runway).
Daily schedule: 2 new videos per category.

Constraints:
  - Max 5 concurrent generations (semaphore)
  - Never store fal.ai or Runway URLs — always Cloudinary
  - Log every generation to AgentMemory
"""
from dotenv import load_dotenv
load_dotenv()

import os, json, threading
from datetime import datetime
from sqlmodel import Session, select

from app.database import engine
from app.models.product import Product
from app.models.collection import Collection

# Max 5 concurrent — protects rate limits on fal.ai and Runway
_semaphore = threading.Semaphore(5)


def _log(product_id, asset_type, prompt_hint, status, cost_usd, cloudinary_url=""):
    try:
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="content_agent",
                memory_type="generation_log",
                content=json.dumps({
                    "product_id":     product_id,
                    "asset_type":     asset_type,
                    "prompt_hint":    prompt_hint[:120],
                    "status":         status,
                    "cost_usd":       cost_usd,
                    "cloudinary_url": cloudinary_url,
                    "timestamp":      datetime.utcnow().isoformat(),
                }),
                confidence=1.0,
            ))
            session.commit()
    except Exception as e:
        print(f"[Content] Log error: {e}")


def generate_product_content(product: Product, with_video: bool = False) -> dict:
    """
    Full image pipeline for one product. Optionally generates a video too.
    Returns dict with URLs saved to product.
    """
    from app.agents.fal_agent import generate_clean_shot, generate_lifestyle_shot
    from app.agents.runway_agent import generate_product_video
    from app.agents.cloudinary_agent import store_product_image, store_product_video

    pid      = product.id
    name     = product.name
    material = product.material or "925 Sterling Silver"
    category = product.category
    result   = {"product_id": pid, "images": {}, "video": None, "total_cost": 0.0}

    with _semaphore:
        # Clean shot
        print(f"[Content] Clean shot: {name}")
        raw_clean = generate_clean_shot(name, material)
        if raw_clean:
            cdn_clean = store_product_image(pid, raw_clean, "clean")
            if cdn_clean:
                result["images"]["clean"] = cdn_clean
                result["total_cost"] += 0.04
                _log(pid, "image_clean", name, "success", 0.04, cdn_clean)
            else:
                _log(pid, "image_clean", name, "cloudinary_fail", 0.04)
        else:
            _log(pid, "image_clean", name, "generation_fail", 0.04)

        # Lifestyle shot (skin tone rotates by product_id)
        print(f"[Content] Lifestyle shot: {name}")
        raw_life = generate_lifestyle_shot(name, material, category, pid)
        if raw_life:
            cdn_life = store_product_image(pid, raw_life, "lifestyle")
            if cdn_life:
                result["images"]["lifestyle"] = cdn_life
                result["total_cost"] += 0.04
                _log(pid, "image_lifestyle", name, "success", 0.04, cdn_life)
            else:
                _log(pid, "image_lifestyle", name, "cloudinary_fail", 0.04)
        else:
            _log(pid, "image_lifestyle", name, "generation_fail", 0.04)

        # Video — uses lifestyle image as Runway input frame
        if with_video:
            input_image = result["images"].get("lifestyle") or result["images"].get("clean")
            if input_image:
                print(f"[Content] Video: {name}")
                raw_video, duration, video_cost = generate_product_video(input_image, category)
                if raw_video:
                    cdn_video = store_product_video(pid, category, raw_video)
                    if cdn_video:
                        result["video"] = cdn_video
                        result["total_cost"] += video_cost
                        _log(pid, "video", name, "success", video_cost, cdn_video)
                    else:
                        _log(pid, "video", name, "cloudinary_fail", video_cost)
                else:
                    _log(pid, "video", name, "generation_fail", video_cost)

    # Save all URLs to product record
    with Session(engine) as session:
        p = session.get(Product, pid)
        if p:
            if result["images"].get("clean"):
                p.content_image_url = result["images"]["clean"]
            if result["images"].get("lifestyle"):
                p.content_lifestyle_url = result["images"]["lifestyle"]
            if result["video"]:
                p.video_url = result["video"]
            p.content_generated_at = datetime.utcnow()
            session.add(p)
            session.commit()

    # Emit to nervous system so ARIA and command center track progress
    try:
        from app.agents.nervous_system import emit
        emit(
            signal_type="CONTENT_READY",
            sender="content_agent",
            payload={
                "product_id":   pid,
                "product_name": name,
                "asset_type":   "video" if result["video"] else "image",
                "images_done":  len(result["images"]),
                "videos_done":  1 if result["video"] else 0,
                "total_cost":   round(result["total_cost"], 4),
            },
            priority=6,
        )
    except Exception as e:
        print(f"[Content] Signal error: {e}")

    print(f"[Content] {name} done — cost ${result['total_cost']:.2f}")
    return result


def generate_collection_content(collection: Collection) -> bool:
    from app.agents.fal_agent import generate_collection_tile_image
    from app.agents.runway_agent import generate_collection_video
    from app.agents.cloudinary_agent import store_product_image, store_collection_video

    cid  = collection.id
    name = collection.name
    print(f"[Content] Collection tile: {name}")

    with _semaphore:
        raw_image = generate_collection_tile_image(name)
        if not raw_image:
            _log(cid, "collection_image", name, "generation_fail", 0.04)
            return False

        cdn_image = store_product_image(cid, raw_image, f"collection_{name.lower()}")
        if not cdn_image:
            _log(cid, "collection_image", name, "cloudinary_fail", 0.04)
            return False

        raw_video, _, cost = generate_collection_video(cdn_image, name)
        if not raw_video:
            _log(cid, "collection_video", name, "generation_fail", cost)
            return False

        cdn_video = store_collection_video(cid, name, raw_video)
        if not cdn_video:
            _log(cid, "collection_video", name, "cloudinary_fail", cost)
            return False

    with Session(engine) as session:
        c = session.get(Collection, cid)
        if c:
            c.video_url = cdn_video
            session.add(c)
            session.commit()

    _log(cid, "collection_video", name, "success", 0.04 + cost, cdn_video)
    print(f"[Content] Collection tile done: {name}")
    return True


def generate_hero_content() -> bool:
    from app.agents.fal_agent import generate_hero_image
    from app.agents.runway_agent import generate_hero_video
    from app.agents.cloudinary_agent import store_product_image, store_hero_video

    print("[Content] Hero banner")
    with _semaphore:
        raw_image = generate_hero_image()
        if not raw_image:
            return False
        cdn_image = store_product_image(0, raw_image, "hero_source")
        if not cdn_image:
            return False

        raw_video, _, cost = generate_hero_video(cdn_image)
        if not raw_video:
            return False

        cdn_video = store_hero_video(raw_video)
        if not cdn_video:
            return False

    from app.agents.store_config import set_config
    set_config("hero_video_url", cdn_video, "Hero banner video — generated by content agent")
    _log(0, "hero_video", "hero banner", "success", 0.04 + cost, cdn_video)
    print(f"[Content] Hero video saved")
    return True


def run_image_pipeline(limit: int = None):
    """Generate images for all products without content_image_url yet."""
    with Session(engine) as session:
        q = select(Product).where(
            Product.is_active == True,
            Product.content_image_url == None,
        )
        products = session.exec(q).all()

    if limit:
        products = products[:limit]

    print(f"[Content] Image pipeline: {len(products)} products")
    total_cost = 0.0
    for p in products:
        r = generate_product_content(p, with_video=False)
        total_cost += r["total_cost"]
    print(f"[Content] Image pipeline complete — total cost ${total_cost:.2f}")
    try:
        from app.agents.nervous_system import emit
        emit(
            signal_type="CONTENT_BATCH_COMPLETE",
            sender="content_agent",
            payload={
                "batch_type":        "image_pipeline",
                "images_generated":  len(products),
                "videos_generated":  0,
                "total_cost":        round(total_cost, 2),
            },
            priority=5,
        )
    except Exception as e:
        print(f"[Content] Batch signal error: {e}")


def run_video_pipeline_initial():
    """
    One-time run: top 20 products by stock + all collections + hero banner.
    Run after images are generated.
    """
    with Session(engine) as session:
        top20 = session.exec(
            select(Product)
            .where(Product.is_active == True, Product.video_url == None)
            .order_by(Product.stock.desc())
            .limit(20)
        ).all()

    print(f"[Content] Initial video pipeline: {len(top20)} products + collections + hero")

    for p in top20:
        generate_product_content(p, with_video=True)

    with Session(engine) as session:
        collections = session.exec(
            select(Collection).where(Collection.is_active == True)
        ).all()

    for c in collections:
        generate_collection_content(c)

    generate_hero_content()
    print("[Content] Initial video pipeline complete.")


def run_daily_video_batch():
    """
    Daily: 2 new videos per category (12/day max).
    Picks newest products without a video, requires content_image_url already set.
    """
    categories = ["Rings", "Necklaces", "Bracelets", "Earrings", "Anklets", "Ear Cuffs"]
    total = 0

    for cat in categories:
        with Session(engine) as session:
            candidates = session.exec(
                select(Product)
                .where(
                    Product.is_active == True,
                    Product.category == cat,
                    Product.video_url == None,
                    Product.content_image_url != None,
                )
                .order_by(Product.id.desc())
                .limit(2)
            ).all()

        for p in candidates:
            generate_product_content(p, with_video=True)
            total += 1

    print(f"[Content] Daily batch done: {total} videos generated")
    _log(0, "daily_batch", str(datetime.utcnow().date()), "complete", 0.0)
    try:
        from app.agents.nervous_system import emit
        emit(
            signal_type="CONTENT_BATCH_COMPLETE",
            sender="content_agent",
            payload={
                "batch_type":        "daily_video_batch",
                "images_generated":  0,
                "videos_generated":  total,
                "total_cost":        round(total * 0.25, 2),
            },
            priority=5,
        )
    except Exception as e:
        print(f"[Content] Batch signal error: {e}")
