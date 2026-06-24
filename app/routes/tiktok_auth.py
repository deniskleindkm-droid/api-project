from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
import os

router = APIRouter(prefix="/auth/tiktok")

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI")


@router.get("/login")
def tiktok_login():
    url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        "&response_type=code"
        "&scope=user.info.basic,video.publish,video.upload"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
        "&state=mikisi_tiktok_auth"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def tiktok_callback(request: Request):
    error = request.query_params.get("error")
    code = request.query_params.get("code")

    if error or not code:
        return JSONResponse(
            status_code=400,
            content={
                "error": error or "missing_code",
                "error_description": request.query_params.get("error_description", "No authorization code returned"),
            },
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": TIKTOK_REDIRECT_URI,
            },
        )

    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"error": "token_exchange_failed", "detail": body},
        )

    open_id = body.get("open_id")
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    refresh_expires_in = body.get("refresh_expires_in")

    print(f"[TikTok Auth] open_id={open_id}")
    print(f"[TikTok Auth] access_token={access_token}")
    print(f"[TikTok Auth] refresh_token={refresh_token}")
    print(f"[TikTok Auth] expires_in={expires_in}")
    print(f"[TikTok Auth] refresh_expires_in={refresh_expires_in}")

    return {
        "message": "TikTok authorization successful. Copy the access_token to Railway as TIKTOK_ACCESS_TOKEN and save the refresh_token somewhere safe.",
        "open_id": open_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
    }


@router.get("/user")
async def tiktok_user_info():
    """
    Calls TikTok's /v2/user/info/ endpoint using the stored access token.
    Used to verify the token is valid and display connected account info.
    """
    from app.agents.tiktok_token import get_access_token
    access_token = get_access_token()

    if not access_token:
        return JSONResponse(
            status_code=400,
            content={"error": "TIKTOK_ACCESS_TOKEN not set in environment variables"},
        )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://open.tiktokapis.com/v2/user/info/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={
                "fields": "open_id,union_id,avatar_url,display_name"
            },
        )

    if response.status_code != 200:
        return JSONResponse(
            status_code=500,
            content={
                "error": "TikTok API call failed",
                "status_code": response.status_code,
                "detail": response.json(),
            },
        )

    data = response.json()
    user = data.get("data", {}).get("user", {})
    print(f"[TikTok] User info fetched — display_name={user.get('display_name')} open_id={user.get('open_id')}")

    return JSONResponse(status_code=200, content=data)


@router.post("/test-post")
async def tiktok_test_post():
    """Temporary endpoint — tests TikTok Direct Post flow (FILE_UPLOAD) with sandbox token."""
    from app.agents.tiktok_token import get_access_token
    access_token = get_access_token()
    video_url = "https://res.cloudinary.com/ds8qviz1o/video/upload/v1780941636/mikisi/videos/rings_571.mp4"

    async with httpx.AsyncClient(timeout=120) as client:
        # Step 1 — download video from Cloudinary
        video_resp = await client.get(video_url)
        video_bytes = video_resp.content
        video_size = len(video_bytes)
        print(f"[TikTok] Downloaded video: {video_size} bytes")

        # Step 2 — init the upload
        init_resp = await client.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "post_info": {
                    "title": "925 sterling silver ring. New arrivals at mikisi.co #jewelry #sterlingsilver #luxury",
                    "privacy_level": "SELF_ONLY",
                    "disable_duet": True,
                    "disable_comment": True,
                    "disable_stitch": True,
                    "brand_content_toggle": False,
                    "brand_organic_toggle": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1,
                },
            },
        )
        init_data = init_resp.json()
        print(f"[TikTok] Init response: {init_resp.status_code} — {init_data}")

        if init_resp.status_code != 200 or "data" not in init_data:
            return JSONResponse(status_code=init_resp.status_code, content=init_data)

        publish_id = init_data["data"]["publish_id"]
        upload_url = init_data["data"]["upload_url"]

        # Step 3 — upload the video bytes
        put_resp = await client.put(
            upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            },
            content=video_bytes,
        )
        print(f"[TikTok] Upload response: {put_resp.status_code}")

    return JSONResponse(status_code=200, content={
        "publish_id": publish_id,
        "upload_status": put_resp.status_code,
        "video_size_bytes": video_size,
    })


@router.post("/test-inbox")
async def tiktok_test_inbox():
    """Temporary endpoint — tests TikTok inbox (unaudited) post flow with sandbox token."""
    from app.agents.tiktok_token import get_access_token
    access_token = get_access_token()
    video_url = "https://res.cloudinary.com/ds8qviz1o/video/upload/v1780941636/mikisi/videos/rings_571.mp4"

    async with httpx.AsyncClient(timeout=120) as client:
        # Step 1 — download video from Cloudinary
        video_resp = await client.get(video_url)
        video_bytes = video_resp.content
        video_size = len(video_bytes)
        print(f"[TikTok Inbox] Downloaded video: {video_size} bytes")

        # Step 2 — init inbox upload
        init_resp = await client.post(
            "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1,
                },
            },
        )
        init_data = init_resp.json()
        print(f"[TikTok Inbox] Init response: {init_resp.status_code} — {init_data}")

        if init_resp.status_code != 200 or "data" not in init_data:
            return JSONResponse(status_code=init_resp.status_code, content=init_data)

        publish_id = init_data["data"]["publish_id"]
        upload_url = init_data["data"]["upload_url"]

        # Step 3 — upload the video bytes
        put_resp = await client.put(
            upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            },
            content=video_bytes,
        )
        print(f"[TikTok Inbox] Upload response: {put_resp.status_code}")

    return JSONResponse(status_code=200, content={
        "publish_id": publish_id,
        "upload_status": put_resp.status_code,
        "video_size_bytes": video_size,
    })


@router.get("/refresh")
async def tiktok_refresh(refresh_token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"error": "token_refresh_failed", "detail": body},
        )

    open_id = body.get("open_id")
    access_token = body.get("access_token")
    new_refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    refresh_expires_in = body.get("refresh_expires_in")

    print(f"[TikTok Auth] Refreshed — open_id={open_id}")
    print(f"[TikTok Auth] access_token={access_token}")
    print(f"[TikTok Auth] refresh_token={new_refresh_token}")
    print(f"[TikTok Auth] expires_in={expires_in}")
    print(f"[TikTok Auth] refresh_expires_in={refresh_expires_in}")

    return {
        "open_id": open_id,
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
    }
