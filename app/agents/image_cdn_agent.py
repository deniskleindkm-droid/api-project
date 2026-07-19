"""
Image CDN Agent
----------------
Routes every product's primary image through Cloudinary instead of
hotlinking Silverbene's origin server directly on every storefront visit.

Measured directly (2026-07-16): Silverbene's own images run 40KB-500KB
each and take 0.5-1.3s per request — no edge caching for us, high origin
latency. Only 2 of 234 published products had a Cloudinary-hosted
content_image_url; the other 232 fell back to the raw Silverbene
image_url on every single page load. This was the dominant cause of slow
image loads on the storefront.

No frontend change needed — docs/index.html's product grid already
prefers content_image_url over image_url (`p.content_image_url ||
p.image_url`) wherever it's set. This agent just makes sure every
product actually has one.

store_product_image() (cloudinary_agent.py) does the real work:
Cloudinary fetches the source URL once, resizes to 1200px, picks
auto:good quality + auto format (WebP/AVIF), and serves the result from
its own edge CDN forever after — decoupling storefront speed from
Silverbene's origin performance entirely.

Two parts:
  1. backfill_product_images() — one-time (but safely rerunnable) sweep
     over the existing catalog. Only touches products missing
     content_image_url, so it's cheap to call again after any bulk import.
  2. Real-time caching for every NEW product happens in
     store_manager.py's add_product_to_store() — the single point both
     import pipelines (bulk_import_agent.py and product_rewriter.py's
     path) converge on, so this can never miss one or the other (see
     memory: feedback_new_imports_must_get_fixes — the exact trap of
     fixing only one of two pipelines).
"""
import time
import json
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product
from app.agents.cloudinary_agent import store_product_image


def backfill_product_images(limit: int = 20, verbose: bool = True) -> dict:
    """
    Uploads image_url to Cloudinary for active products missing
    content_image_url, storing the result. Processes at most `limit`
    products per call — deliberately small, since each upload round-trips
    through Silverbene's slow origin (Cloudinary fetches it once, but that
    fetch itself can take 1-2s) and this is meant to be called repeatedly
    from an HTTP-triggered admin endpoint that shouldn't risk a request
    timeout. Returns {"scanned": n, "succeeded": n, "failed": [ids]} —
    call again while "scanned" > 0 to keep working through the backlog.
    """
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.content_image_url == None,
                Product.image_url != None,
                Product.image_url != "",
            ).limit(limit)
        ).all()

    if verbose:
        print(f"[Image CDN] Processing {len(products)} product(s) missing content_image_url")

    succeeded, failed = 0, []
    for p in products:
        url = store_product_image(p.id, p.image_url, "primary")
        if url:
            with Session(engine) as session:
                product = session.get(Product, p.id)
                if product:
                    product.content_image_url = url
                    session.add(product)
                    session.commit()
            succeeded += 1
            if verbose:
                print(f"[Image CDN] #{p.id} {p.name[:40]} -> cached")
        else:
            failed.append(p.id)
            if verbose:
                print(f"[Image CDN] #{p.id} {p.name[:40]} -> FAILED")
        time.sleep(0.3)  # polite pacing against Silverbene's origin + Cloudinary rate limits

    result = {"scanned": len(products), "succeeded": succeeded, "failed": failed}
    if verbose:
        print(f"[Image CDN] Done — {succeeded} succeeded, {len(failed)} failed")
    return result


def backfill_product_galleries(limit: int = 20, verbose: bool = True) -> dict:
    """
    Same idea as backfill_product_images(), for the full gallery (`images`)
    instead of just the primary photo. Added 2026-07-19 after Instagram
    carousel posts hotlinking raw Silverbene gallery URLs hit real
    intermittent 503s from their CDN — content_image_url (primary) was
    already Cloudinary-cached and never had this problem; content_images
    (gallery) didn't exist yet. Only touches products with a real gallery
    and no content_images yet, so it's cheap and safe to rerun. Call
    repeatedly (like backfill_product_images) while "scanned" > 0.
    """
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.content_images == None,
                Product.images != None,
                Product.images != "",
            ).limit(limit)
        ).all()

    if verbose:
        print(f"[Image CDN] Processing {len(products)} product(s) missing content_images")

    succeeded, failed = 0, []
    for p in products:
        try:
            gallery = json.loads(p.images) if p.images else []
        except Exception:
            gallery = []
        if not gallery:
            continue

        cached = []
        for i, url in enumerate(gallery):
            if not url:
                continue
            result_url = store_product_image(p.id, url, f"gallery_{i}")
            cached.append(result_url or url)  # keep original as fallback rather than drop the slot
            time.sleep(0.3)

        if cached:
            with Session(engine) as session:
                product = session.get(Product, p.id)
                if product:
                    product.content_images = json.dumps(cached)
                    session.add(product)
                    session.commit()
            succeeded += 1
            if verbose:
                print(f"[Image CDN] #{p.id} {p.name[:40]} -> gallery cached ({len(cached)} images)")
        else:
            failed.append(p.id)
            if verbose:
                print(f"[Image CDN] #{p.id} {p.name[:40]} -> FAILED")

    result = {"scanned": len(products), "succeeded": succeeded, "failed": failed}
    if verbose:
        print(f"[Image CDN] Gallery backfill done — {succeeded} succeeded, {len(failed)} failed")
    return result
