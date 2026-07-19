"""
Cloudinary storage layer — all generated assets pass through here.
Never save fal.ai or Runway URLs to the DB — they expire.
Always upload to Cloudinary first, then save the Cloudinary URL.
"""
import os
import cloudinary
import cloudinary.uploader
import cloudinary.api

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

FOLDER_IMAGES = "mikisi/products"
FOLDER_VIDEOS = "mikisi/videos"
FOLDER_COLLECTIONS = "mikisi/collections"


def _shrink_local_image_if_needed(path: str, max_bytes: int = 9_500_000) -> str:
    """
    Cloudinary's plan caps a single image upload at 10MB — hit directly by
    a RAWSHOT photoshoot export (10,874,565 bytes, lossless PNG). Only
    touches local files over the limit; remote URLs and files already
    under it pass through untouched (Cloudinary's own auto quality/format
    already handles those on its end).

    Downscales to a max 2400px side and re-encodes as JPEG (photographic
    AI-generated content compresses far better as JPEG than lossless PNG),
    stepping quality down until it clears the limit. Returns the original
    path if this isn't a local file at all.
    """
    if not os.path.isfile(path):
        return path
    if os.path.getsize(path) <= max_bytes:
        return path

    from PIL import Image
    import tempfile
    img = Image.open(path).convert("RGB")
    max_dim = 2400
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))

    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    quality = 90
    while quality >= 50:
        img.save(tmp_path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(tmp_path) <= max_bytes:
            break
        quality -= 10
    return tmp_path


def _upload_image(url: str, public_id: str, tags: list) -> str:
    upload_source = _shrink_local_image_if_needed(url)
    result = cloudinary.uploader.upload(
        upload_source,
        public_id=public_id,
        overwrite=True,
        resource_type="image",
        # auto:good balances quality vs file size — fast on mobile without looking cheap
        quality="auto:good",
        fetch_format="auto",          # WebP/AVIF on supported browsers
        width=1200, crop="limit",     # cap at 1200px — enough for retina, not wasteful
        tags=tags,
    )
    return result.get("secure_url", "")


def _upload_video(url: str, public_id: str, tags: list) -> str:
    result = cloudinary.uploader.upload(
        url,
        public_id=public_id,
        overwrite=True,
        resource_type="video",
        # Cloudinary transcodes to H.264 + AAC, normalises bitrate for mobile
        video_codec="auto",
        audio_codec="none",           # jewelry videos have no audio
        quality="auto",
        tags=tags,
    )
    return result.get("secure_url", "")


def store_product_image(product_id: int, image_url: str, variant: str, retries: int = 3) -> str:
    """
    variant: 'clean' | 'lifestyle_dark' | 'lifestyle_light' | 'primary'
    Returns permanent Cloudinary URL or '' on failure.

    Retries on failure — Silverbene's media CDN intermittently 503s on
    individual requests (seen directly while sourcing hero photos; see
    store_hero_rotation_image), and a fetch-by-URL upload of a Silverbene
    image_url hits the same origin. Also used for 'primary' by
    image_cdn_agent.py to mirror image_url itself onto Cloudinary — see
    that module's docstring for why every product needs this, not just
    the AI-generated variants.
    """
    import time
    public_id = f"{FOLDER_IMAGES}/{product_id}_{variant}"
    last_err = None
    for attempt in range(retries):
        try:
            return _upload_image(image_url, public_id, ["mikisi", "product", variant])
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    print(f"[Cloudinary] Image upload failed product={product_id} variant={variant} after {retries} attempts: {last_err}")
    return ""


def delete_product_assets(product_id: int) -> bool:
    """
    Deletes every Cloudinary asset for this product (primary, gallery,
    lifestyle/hero, video) in one call — every public_id for a product shares
    the `{FOLDER_IMAGES}/{product_id}_` prefix (see store_product_image), so
    a prefix delete catches all variants without needing to track each one.
    Called when a product is permanently removed from the database (see
    silverbene_discontinuation_agent.py's 7-day deletion sweep) — Dennis
    pays for Cloudinary storage monthly and it should never hold orphaned
    assets for a product that no longer exists.
    """
    try:
        cloudinary.api.delete_resources_by_prefix(f"{FOLDER_IMAGES}/{product_id}_")
        return True
    except Exception as e:
        print(f"[Cloudinary] Asset cleanup failed for product={product_id}: {e}")
        return False


def store_product_video(product_id: int, category: str, video_url: str) -> str:
    public_id = f"{FOLDER_VIDEOS}/{category.lower()}_{product_id}"
    try:
        return _upload_video(video_url, public_id, ["mikisi", "video", category.lower()])
    except Exception as e:
        print(f"[Cloudinary] Video upload failed product={product_id}: {e}")
        return ""


def store_collection_video(collection_id: int, collection_name: str, video_url: str) -> str:
    public_id = f"{FOLDER_COLLECTIONS}/{collection_name.lower().replace(' ', '_')}_{collection_id}"
    try:
        return _upload_video(video_url, public_id, ["mikisi", "collection_video"])
    except Exception as e:
        print(f"[Cloudinary] Collection video upload failed collection={collection_id}: {e}")
        return ""


def store_hero_video(video_url: str) -> str:
    try:
        return _upload_video(video_url, "mikisi/hero/banner_video", ["mikisi", "hero"])
    except Exception as e:
        print(f"[Cloudinary] Hero video upload failed: {e}")
        return ""


def store_hero_image(image_source: str) -> str:
    """image_source: a URL or a local file path — Cloudinary's SDK accepts either."""
    try:
        result = cloudinary.uploader.upload(
            image_source,
            public_id="mikisi/hero/banner_image",
            overwrite=True,
            resource_type="image",
            quality="auto:good",
            fetch_format="auto",
            width=1920, crop="limit",
            tags=["mikisi", "hero"],
        )
        return result.get("secure_url", "")
    except Exception as e:
        print(f"[Cloudinary] Hero image upload failed: {e}")
        return ""


def store_hero_rotation_image(slot: int, image_source: str, retries: int = 3) -> str:
    """
    One of a fixed set of hero rotation slots (0-based) — Dennis picks which
    product photo goes in each slot. Re-uses the same public_id every time a
    slot is (re)populated so the URL a slot resolves to stays stable even as
    which product occupies it changes — no URL churn for caching/CDN.

    Silverbene's media CDN intermittently 503s on individual requests (seen
    directly while sourcing hero photos), so a fetch-by-URL upload gets a
    few retries before giving up on this slot.
    """
    import time
    last_err = None
    for attempt in range(retries):
        try:
            result = cloudinary.uploader.upload(
                image_source,
                public_id=f"mikisi/hero/rotation_{slot}",
                overwrite=True,
                resource_type="image",
                quality="auto:good",
                fetch_format="auto",
                width=1920, crop="limit",
                tags=["mikisi", "hero", "hero_rotation"],
            )
            return result.get("secure_url", "")
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    print(f"[Cloudinary] Hero rotation image upload failed (slot {slot}) after {retries} attempts: {last_err}")
    return ""
