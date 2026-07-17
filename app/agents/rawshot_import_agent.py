"""
RAWSHOT Photoshoot Import Agent
--------------------------------
Watches a fixed local folder for RAWSHOT photoshoot exports and wires them
into the matching store product — no manual per-photo tagging needed.

Folder: C:\\Users\\macho\\OneDrive\\Desktop\\insta images (permanent location,
confirmed by Dennis 2026-07-16 — drop new zips here anytime).

Each export is a zip named "<product-slug>-photoshoot-with-<model>-<date>-
<uuid>.zip" containing 1-3 files named "00N-image-<uuid>.png" /
"00N-video-<uuid>.mp4" (count and mix vary per product — some are a single
image, some add a video, some have multiple images).

Matching is by EXACT slugified product name only — a folder/zip that
doesn't match anything is reported, never guessed. Confirmed near-misses
(e.g. RAWSHOT's own slug dropping a word the real product name has) go in
MANUAL_SLUG_OVERRIDES only after Dennis explicitly confirms which product
they mean — same "never guess" principle as everywhere else in this
pipeline (see memory: feedback_silverbene_ground_truth).

Uploads the lowest-numbered image as content_lifestyle_url (this is what
instagram_agent.py's campaign-post picker should prefer over the generic
gallery-photo fallback it uses today — see _best_campaign_image), any
additional images appended to the product's existing images gallery
(already powers the grid's hover-swap-to-second-photo feature), and the
video (if present) as video_url. All three fields already exist on
Product — nothing new needed there.

Safe to rerun: successfully processed zips are moved into a "processed"
subfolder so a rerun only touches new drops, and gallery appends check
for the URL already being present first (Cloudinary re-uploads are
naturally idempotent via a deterministic public_id, but the DB-side
gallery list append is not, without this guard).
"""
import os
import re
import json
import zipfile
import tempfile
import shutil
import requests

from app.agents.cloudinary_agent import store_product_image, store_product_video

FOLDER = r"C:\Users\macho\OneDrive\Desktop\insta images"
PROCESSED_SUBFOLDER = "processed"
API = "https://api-project-production-d424.up.railway.app"

# Confirmed exceptions where the RAWSHOT slug doesn't exactly match the
# live product name. Only add an entry here after explicit confirmation —
# never auto-fuzzy-match a slug to a product.
MANUAL_SLUG_OVERRIDES = {
    "cubic-zirconia-station-necklace": 1075,  # real name: "...Station Chain Necklace" — confirmed 2026-07-16
}


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _get_all_products(session=requests):
    r = session.get(f"{API}/products", params={"limit": 1000}, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_product(pid: int, master_key: str):
    r = requests.get(f"{API}/products/{pid}", params={"preview_key": master_key}, timeout=30)
    r.raise_for_status()
    return r.json()


def _save_product(pid: int, fields: dict):
    r = requests.put(f"{API}/products/{pid}", json=fields, timeout=60)
    r.raise_for_status()
    return r.json()


def run_rawshot_import(master_key: str, folder: str = FOLDER, verbose: bool = True) -> dict:
    """
    Processes every zip currently in `folder` (skips the processed/
    subfolder itself). Returns a summary dict; moves each successfully
    handled zip into folder/processed/ so future calls only see new drops.
    """
    if not os.path.isdir(folder):
        return {"error": f"folder not found: {folder}"}

    processed_dir = os.path.join(folder, PROCESSED_SUBFOLDER)
    os.makedirs(processed_dir, exist_ok=True)

    products = _get_all_products()
    by_slug = {_slugify(p["name"]): p for p in products}

    zips = [f for f in os.listdir(folder) if f.lower().endswith(".zip")]
    result = {"matched": [], "unmatched": [], "errors": []}

    if verbose:
        print(f"[RAWSHOT Import] {len(zips)} zip(s) to process in {folder}")

    for fname in zips:
        m = re.match(r"^(.*?)-photoshoot-with-", fname)
        if not m:
            result["unmatched"].append({"file": fname, "reason": "unrecognized filename pattern"})
            if verbose:
                print(f"[RAWSHOT Import] SKIP (unrecognized pattern): {fname}")
            continue
        slug = m.group(1)

        product = by_slug.get(slug)
        pid = product["id"] if product else MANUAL_SLUG_OVERRIDES.get(slug)
        if not pid:
            result["unmatched"].append({"file": fname, "slug": slug, "reason": "no matching product"})
            if verbose:
                print(f"[RAWSHOT Import] NO MATCH for slug '{slug}' ({fname}) — skipping, not guessing")
            continue

        try:
            detail = _get_product(pid, master_key)
            category = detail.get("category", "")
            if verbose:
                print(f"[RAWSHOT Import] {fname} -> #{pid} {detail['name']!r} ({category})")

            zpath = os.path.join(folder, fname)
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(zpath) as zf:
                    zf.extractall(tmp)
                    names = sorted(zf.namelist())

                images = [n for n in names if "-image-" in n]
                videos = [n for n in names if "-video-" in n]

                uploaded_image_urls = []
                for i, img_name in enumerate(images):
                    local_path = os.path.join(tmp, img_name)
                    variant = "lifestyle" if i == 0 else f"lifestyle_{i + 1}"
                    url = store_product_image(pid, local_path, variant)
                    if url:
                        uploaded_image_urls.append(url)
                        if verbose:
                            print(f"[RAWSHOT Import]   image {img_name} -> {variant}")
                    elif verbose:
                        print(f"[RAWSHOT Import]   image {img_name} -> UPLOAD FAILED")

                uploaded_video_url = None
                for vid_name in videos:
                    local_path = os.path.join(tmp, vid_name)
                    url = store_product_video(pid, category, local_path)
                    if url:
                        uploaded_video_url = url
                        if verbose:
                            print(f"[RAWSHOT Import]   video {vid_name} -> uploaded")
                    elif verbose:
                        print(f"[RAWSHOT Import]   video {vid_name} -> UPLOAD FAILED")

            fields = {}
            if uploaded_image_urls:
                fields["content_lifestyle_url"] = uploaded_image_urls[0]
                extra = uploaded_image_urls[1:]
                if extra:
                    try:
                        existing_gallery = list(json.loads(detail.get("images") or "[]"))
                    except Exception:
                        existing_gallery = []
                    for url in extra:
                        if url not in existing_gallery:
                            existing_gallery.append(url)
                    fields["images"] = json.dumps(existing_gallery)
            if uploaded_video_url:
                fields["video_url"] = uploaded_video_url

            if fields:
                _save_product(pid, fields)

            shutil.move(zpath, os.path.join(processed_dir, fname))
            result["matched"].append({"file": fname, "product_id": pid, "fields": list(fields.keys())})

        except Exception as e:
            result["errors"].append({"file": fname, "error": str(e)})
            if verbose:
                print(f"[RAWSHOT Import]   ERROR: {e}")

    if verbose:
        print(f"[RAWSHOT Import] Done — {len(result['matched'])} matched, "
              f"{len(result['unmatched'])} unmatched, {len(result['errors'])} errors")
    return result


if __name__ == "__main__":
    import os as _os
    from dotenv import load_dotenv
    load_dotenv()
    run_rawshot_import(master_key=_os.getenv("ARIA_MASTER_KEY", ""))
