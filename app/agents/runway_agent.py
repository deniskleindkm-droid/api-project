"""
Runway ML Gen-3 Alpha — product and collection videos for Mikisi.
Takes a fal.ai-generated image as the input frame, adds motion on top.
Videos: top 20 products + 6 collection tiles + 1 hero banner.
Daily: 2 new videos per category (12/day).
Cost: ~$0.25 per 5s clip, ~$0.30 per 6s clip, ~$0.50 per 10s hero.
"""
import os
import time
import requests

RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
RUNWAY_BASE    = "https://api.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"
POLL_INTERVAL  = 10   # seconds between status checks
POLL_TIMEOUT   = 300  # 5 minutes max wait

HEADERS = {
    "Authorization": f"Bearer {RUNWAY_API_KEY}",
    "X-Runway-Version": RUNWAY_VERSION,
    "Content-Type": "application/json",
}

# Motion prompts per category — applied on top of the fal.ai input image
CATEGORY_MOTION = {
    "rings":     ("Light moves slowly across the ring, catching the stone once and holding, "
                  "fingers breathe very slowly, 5 seconds, almost still, elegant intimate",
                  5),
    "necklaces": ("Light moves slowly left to right across the necklace catching silver and stone, "
                  "breathing motion on skin, 5 seconds, seamless, no sudden movement",
                  5),
    "bracelets": ("Light moves across the stones slowly, wrist shifts weight once, "
                  "5 seconds, elegant loop",
                  5),
    "earrings":  ("Hair shifts gently once then settles, earring catches light, "
                  "5 seconds, slow intimate",
                  5),
    "anklets":   ("Foot shifts weight softly once, anklet catches light, "
                  "6 seconds, golden afternoon feel",
                  6),
    "ear cuffs": ("Hair settles back slowly over ear, ear cuff visible in full light, "
                  "5 seconds total, intimate close-up",
                  5),
}

COLLECTION_MOTION = (
    "Cinematic slow drift across jewelry pieces on cream marble surface, "
    "light moves gently catching silver details, "
    "6 seconds seamless loop, luxury editorial",
    6,
)

HERO_MOTION = (
    "Cinematic light drift across silver jewelry on warm skin, "
    "cream and gold tones, slow pan left to right, "
    "10 seconds seamless loop, luxury editorial, Tiffany atmosphere, "
    "empowering intimate",
    10,
)


def _create_task(image_url: str, prompt: str, duration: int) -> str:
    """Submit a generation task. Returns task_id or ''."""
    try:
        r = requests.post(
            f"{RUNWAY_BASE}/image_to_video",
            headers=HEADERS,
            json={
                "model":        "gen3a_turbo",
                "promptImage":  image_url,
                "promptText":   prompt,
                "duration":     duration,
                "ratio":        "768:1280",  # portrait 9:16 for social
            },
            timeout=30,
        )
        data = r.json()
        task_id = data.get("id", "")
        if not task_id:
            print(f"[Runway] Task creation failed: {data}")
        return task_id
    except Exception as e:
        print(f"[Runway] Task creation error: {e}")
        return ""


def _poll_task(task_id: str) -> str:
    """Poll until SUCCEEDED. Returns video URL or ''."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{RUNWAY_BASE}/tasks/{task_id}",
                headers=HEADERS,
                timeout=30,
            )
            data = r.json()
            status = data.get("status", "")

            if status == "SUCCEEDED":
                outputs = data.get("output", [])
                return outputs[0] if outputs else ""

            if status in ("FAILED", "CANCELLED"):
                print(f"[Runway] Task {task_id} ended with status: {status}")
                return ""

            print(f"[Runway] Task {task_id} status: {status} — waiting {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"[Runway] Poll error for {task_id}: {e}")
            time.sleep(POLL_INTERVAL)

    print(f"[Runway] Task {task_id} timed out after {POLL_TIMEOUT}s")
    return ""


def generate_product_video(image_url: str, category: str) -> tuple:
    """
    Generate a product video from a lifestyle image.
    Returns (video_url, duration_seconds, cost_usd).
    image_url must be a permanent URL (Cloudinary) — not fal.ai (expires).
    """
    prompt, duration = CATEGORY_MOTION.get(
        category.lower(), CATEGORY_MOTION["necklaces"]
    )
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05  # Runway Gen-3 ~$0.05/second
    return video_url, duration, cost


def generate_collection_video(image_url: str, collection_name: str) -> tuple:
    """Collection tile video — 6 seconds."""
    prompt_base, duration = COLLECTION_MOTION
    prompt = f"{prompt_base}, {collection_name} collection"
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05
    return video_url, duration, cost


def generate_hero_video(image_url: str) -> tuple:
    """Hero banner video — 10 seconds."""
    prompt, duration = HERO_MOTION
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05
    return video_url, duration, cost
