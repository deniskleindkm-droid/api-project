"""
Mikisi Content Agent — orchestrates the full media pipeline.
Every step emits a nervous system signal so ARIA can track, report, and alert Dennis.
"""
from dotenv import load_dotenv
load_dotenv()

import os, json, threading
from datetime import datetime
from sqlmodel import Session, select

from app.database import engine
from app.models.product import Product
from app.models.collection import Collection

_semaphore = threading.Semaphore(5)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(product_id, asset_type, status, cost_usd, cloudinary_url="", detail=""):
    try:
        from app.models.agent import AgentMemory
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name="content_agent",
                memory_type="generation_log",
                content=json.dumps({
                    "product_id":     product_id,
                    "asset_type":     asset_type,
                    "status":         status,
                    "cost_usd":       cost_usd,
                    "cloudinary_url": cloudinary_url,
                    "detail":         detail,
                    "timestamp":      datetime.utcnow().isoformat(),
                }),
                confidence=1.0,
            ))
            session.commit()
    except Exception as e:
        print(f"[Content] Log error: {e}")


def _signal(signal_type, payload, priority=6):
    try:
        from app.agents.nervous_system import emit
        emit(signal_type=signal_type, sender="content_agent",
             payload=payload, priority=priority)
    except Exception as e:
        print(f"[Content] Signal error ({signal_type}): {e}")


def _fail(asset_type, name, reason):
    """Emit CONTENT_FAILED — nervous system will email Dennis immediately."""
    print(f"[Content] FAILED — {asset_type} for '{name}': {reason}")
    _log(0, asset_type, "failed", 0, detail=f"{name}: {reason}")
    _signal("CONTENT_FAILED", {
        "asset_type": asset_type,
        "name":       name,
        "reason":     reason,
        "timestamp":  datetime.utcnow().isoformat(),
    }, priority=8)


# ── Per-product pipeline ──────────────────────────────────────────────────────

def generate_product_content(product: Product, with_video: bool = False) -> dict:
    from app.agents.fal_agent import generate_clean_shot, generate_lifestyle_shot
    from app.agents.runway_agent import generate_product_video
    from app.agents.cloudinary_agent import store_product_image, store_product_video

    pid      = product.id
    name     = product.name
    material = product.material or "925 Sterling Silver"
    category = product.category
    result   = {"product_id": pid, "images": {}, "video": None, "total_cost": 0.0}

    with _semaphore:
        # ── Clean shot ────────────────────────────────────────────────
        print(f"[Content] [{pid}] Step 1/3 — clean shot: {name}")
        raw_clean = generate_clean_shot(name, material)
        if raw_clean:
            cdn_clean = store_product_image(pid, raw_clean, "clean")
            if cdn_clean:
                result["images"]["clean"] = cdn_clean
                result["total_cost"] += 0.04
                print(f"[Content] [{pid}] Clean shot saved: {cdn_clean[:60]}...")
                _log(pid, "image_clean", "success", 0.04, cdn_clean)
            else:
                _fail("image_clean", name, "Cloudinary upload failed")
        else:
            _fail("image_clean", name, "fal.ai generation returned empty")

        # ── Lifestyle shot ────────────────────────────────────────────
        print(f"[Content] [{pid}] Step 2/3 — lifestyle shot: {name}")
        raw_life = generate_lifestyle_shot(name, material, category, pid)
        if raw_life:
            cdn_life = store_product_image(pid, raw_life, "lifestyle")
            if cdn_life:
                result["images"]["lifestyle"] = cdn_life
                result["total_cost"] += 0.04
                print(f"[Content] [{pid}] Lifestyle saved: {cdn_life[:60]}...")
                _log(pid, "image_lifestyle", "success", 0.04, cdn_life)
            else:
                _fail("image_lifestyle", name, "Cloudinary upload failed")
        else:
            _fail("image_lifestyle", name, "fal.ai generation returned empty")

        # ── Video ─────────────────────────────────────────────────────
        if with_video:
            input_image = result["images"].get("lifestyle") or result["images"].get("clean")
            if input_image:
                print(f"[Content] [{pid}] Step 3/3 — Runway video: {name}")
                raw_video, duration, video_cost = generate_product_video(input_image, category)
                if raw_video:
                    cdn_video = store_product_video(pid, category, raw_video)
                    if cdn_video:
                        result["video"] = cdn_video
                        result["total_cost"] += video_cost
                        print(f"[Content] [{pid}] Video saved: {cdn_video[:60]}...")
                        _log(pid, "video", "success", video_cost, cdn_video)
                    else:
                        _fail("video", name, "Cloudinary video upload failed")
                else:
                    _fail("video", name, "Runway returned empty — task may have failed or timed out")
            else:
                _fail("video", name, "No input image available for Runway")

    # ── Save URLs to DB ───────────────────────────────────────────────
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

    # ── Signal success ────────────────────────────────────────────────
    _signal("CONTENT_READY", {
        "product_id":   pid,
        "product_name": name,
        "category":     category,
        "images_done":  len(result["images"]),
        "videos_done":  1 if result["video"] else 0,
        "total_cost":   round(result["total_cost"], 4),
        "image_url":    result["images"].get("clean", ""),
        "video_url":    result.get("video", ""),
    })

    print(f"[Content] [{pid}] Complete — ${result['total_cost']:.2f}")
    return result


# ── Collection tile ───────────────────────────────────────────────────────────

def generate_collection_content(collection: Collection) -> bool:
    from app.agents.fal_agent import generate_collection_tile_image
    from app.agents.runway_agent import generate_collection_video
    from app.agents.cloudinary_agent import store_product_image, store_collection_video

    cid  = collection.id
    name = collection.name
    print(f"[Content] Collection tile — Step 1/2 image: {name}")

    with _semaphore:
        raw_image = generate_collection_tile_image(name)
        if not raw_image:
            _fail("collection_image", name, "fal.ai returned empty")
            return False

        cdn_image = store_product_image(cid, raw_image, f"collection_{name.lower()}")
        if not cdn_image:
            _fail("collection_image", name, "Cloudinary upload failed")
            return False

        print(f"[Content] Collection tile — Step 2/2 video: {name}")
        raw_video, _, cost = generate_collection_video(cdn_image, name)
        if not raw_video:
            _fail("collection_video", name, "Runway returned empty")
            return False

        cdn_video = store_collection_video(cid, name, raw_video)
        if not cdn_video:
            _fail("collection_video", name, "Cloudinary video upload failed")
            return False

    with Session(engine) as session:
        c = session.get(Collection, cid)
        if c:
            c.video_url = cdn_video
            session.add(c)
            session.commit()

    _log(cid, "collection_video", "success", 0.04 + cost, cdn_video)
    _signal("CONTENT_READY", {
        "product_id":   cid,
        "product_name": f"{name} Collection",
        "category":     "collection",
        "images_done":  1,
        "videos_done":  1,
        "video_url":    cdn_video,
    })
    print(f"[Content] Collection tile done: {name}")
    return True


# ── Hero banner ───────────────────────────────────────────────────────────────

def generate_hero_content() -> bool:
    from app.agents.fal_agent import generate_hero_image
    from app.agents.runway_agent import generate_hero_video
    from app.agents.cloudinary_agent import store_product_image, store_hero_video

    print("[Content] Hero — Step 1/2: generating image via fal.ai")
    with _semaphore:
        raw_image = generate_hero_image()
        if not raw_image:
            _fail("hero_image", "Hero Banner", "fal.ai returned empty")
            return False

        cdn_image = store_product_image(0, raw_image, "hero_source")
        if not cdn_image:
            _fail("hero_image", "Hero Banner", "Cloudinary upload failed")
            return False

        print("[Content] Hero — Step 2/2: generating video via Runway (~2 min)")
        raw_video, _, cost = generate_hero_video(cdn_image)
        if not raw_video:
            _fail("hero_video", "Hero Banner", "Runway returned empty — check Runway API key and task status")
            return False

        cdn_video = store_hero_video(raw_video)
        if not cdn_video:
            _fail("hero_video", "Hero Banner", "Cloudinary video upload failed")
            return False

    from app.agents.store_config import set_config
    set_config("hero_video_url", cdn_video, "Hero banner video")
    _log(0, "hero_video", "success", 0.04 + cost, cdn_video)

    # Emit with high priority — ARIA emails Dennis immediately
    _signal("CONTENT_BATCH_COMPLETE", {
        "batch_type":        "hero_video",
        "images_generated":  1,
        "videos_generated":  1,
        "total_cost":        round(0.04 + cost, 2),
        "hero_video_url":    cdn_video,
    }, priority=7)

    print(f"[Content] Hero video live: {cdn_video}")
    return True


# ── Batch runners ─────────────────────────────────────────────────────────────

def run_image_pipeline(limit: int = None):
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.content_image_url == None,
            )
        ).all()

    if limit:
        products = products[:limit]

    total   = len(products)
    done    = 0
    cost    = 0.0
    failed  = 0

    print(f"[Content] Image pipeline starting: {total} products")

    for p in products:
        r = generate_product_content(p, with_video=False)
        cost += r["total_cost"]
        if r["images"]:
            done += 1
        else:
            failed += 1
        print(f"[Content] Progress: {done+failed}/{total} done ({failed} failed)")

    print(f"[Content] Image pipeline complete — {done} ok, {failed} failed, ${cost:.2f}")
    _signal("CONTENT_BATCH_COMPLETE", {
        "batch_type":        "image_pipeline",
        "images_generated":  done,
        "videos_generated":  0,
        "failed":            failed,
        "total_cost":        round(cost, 2),
    }, priority=7)


def run_video_pipeline_initial():
    with Session(engine) as session:
        top20 = session.exec(
            select(Product)
            .where(Product.is_active == True, Product.video_url == None)
            .order_by(Product.stock.desc())
            .limit(20)
        ).all()

    print(f"[Content] Initial video pipeline: {len(top20)} products + collections + hero")
    videos = 0

    for p in top20:
        r = generate_product_content(p, with_video=True)
        if r["video"]:
            videos += 1

    with Session(engine) as session:
        collections = session.exec(
            select(Collection).where(Collection.is_active == True)
        ).all()

    for c in collections:
        if generate_collection_content(c):
            videos += 1

    if generate_hero_content():
        videos += 1

    _signal("CONTENT_BATCH_COMPLETE", {
        "batch_type":        "initial_video_pipeline",
        "images_generated":  len(top20),
        "videos_generated":  videos,
        "total_cost":        round(videos * 0.30, 2),
    }, priority=7)

    print(f"[Content] Initial pipeline complete — {videos} videos")


def run_daily_video_batch():
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
            r = generate_product_content(p, with_video=True)
            if r["video"]:
                total += 1

    print(f"[Content] Daily batch done: {total} videos")
    _signal("CONTENT_BATCH_COMPLETE", {
        "batch_type":        "daily_video_batch",
        "images_generated":  0,
        "videos_generated":  total,
        "total_cost":        round(total * 0.30, 2),
    }, priority=7)
