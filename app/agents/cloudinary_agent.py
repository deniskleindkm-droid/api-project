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


def _upload_image(url: str, public_id: str, tags: list) -> str:
    result = cloudinary.uploader.upload(
        url,
        public_id=public_id,
        overwrite=True,
        resource_type="image",
        quality="auto:best",
        fetch_format="auto",
        tags=tags,
    )
    return result.get("secure_url", "")


def _upload_video(url: str, public_id: str, tags: list) -> str:
    result = cloudinary.uploader.upload(
        url,
        public_id=public_id,
        overwrite=True,
        resource_type="video",
        tags=tags,
    )
    return result.get("secure_url", "")


def store_product_image(product_id: int, image_url: str, variant: str) -> str:
    """
    variant: 'clean' | 'lifestyle_dark' | 'lifestyle_light'
    Returns permanent Cloudinary URL or '' on failure.
    """
    public_id = f"{FOLDER_IMAGES}/{product_id}_{variant}"
    try:
        return _upload_image(image_url, public_id, ["mikisi", "product", variant])
    except Exception as e:
        print(f"[Cloudinary] Image upload failed product={product_id} variant={variant}: {e}")
        return ""


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
