"""Multi-platform upload — TikTok, Instagram, Facebook, auto-reframe.

Each platform has its own API + authentication flow. All require the user
to create a developer app on the respective platform.

  - TikTok: TikTok Research API / Content Posting API
  - Instagram: Instagram Graph API (requires Facebook Business account)
  - Facebook: Facebook Graph API (same as Instagram)
  - Auto-reframe: FFmpeg's `autoreframe` filter (or crop-based fallback)
    to convert landscape → portrait / square automatically.

When API keys aren't configured, the functions return clear "not configured"
messages — the pipeline never breaks.
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd

log = get_logger("platform_upload")


# ----------------------------------------------------- auto-reframe

async def auto_reframe(video_path: str, target_aspect: str = "portrait",
                        out_path: str | None = None) -> dict:
    """Convert a video from one aspect ratio to another.

    Uses FFmpeg's crop filter to center-crop the video to the target aspect.
    - portrait: 9:16 (1080x1920) — for TikTok / Reels / Shorts
    - square: 1:1 (1080x1080) — for Instagram feed
    - landscape: 16:9 (1920x1080) — for YouTube

    Returns {path, success, from_aspect, to_aspect}.
    """
    src = Path(video_path)
    if not src.exists():
        return {"success": False, "reason": "video not found"}
    out = Path(out_path) if out_path else src.with_suffix(f".{target_aspect}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    sizes = {
        "portrait": (1080, 1920),
        "square": (1080, 1080),
        "landscape": (1920, 1080),
    }
    w, h = sizes.get(target_aspect, (1080, 1920))
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
          f"crop={w}:{h},fps=30,setsar=1,format=yuv420p")
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ])
    if rc != 0:
        return {"success": False, "reason": f"ffmpeg failed: {err[-200:]}"}
    log.info("auto-reframed %s → %s (%s)", src.name, out.name, target_aspect)
    return {"success": True, "path": str(out),
            "to_aspect": target_aspect, "size": f"{w}x{h}"}


async def reframe_for_all_platforms(video_path: str) -> dict:
    """Generate portrait + square + landscape versions of a video.

    Returns {portrait: {path}, square: {path}, landscape: {path}}.
    """
    import asyncio
    results = await asyncio.gather(
        auto_reframe(video_path, "portrait"),
        auto_reframe(video_path, "square"),
        auto_reframe(video_path, "landscape"),
        return_exceptions=True,
    )
    out = {}
    for aspect, r in zip(["portrait", "square", "landscape"], results):
        if isinstance(r, Exception):
            out[aspect] = {"success": False, "reason": str(r)}
        else:
            out[aspect] = r
    return out


# ----------------------------------------------------- TikTok upload

async def upload_to_tiktok(video_path: str, title: str, hashtags: list[str],
                            cover_path: str | None = None) -> dict:
    """Upload a video to TikTok via the Content Posting API.

    Requires TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET in .env.
    When not configured, returns a clear "not configured" message.
    """
    import os
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not client_key or not client_secret:
        return {"success": False,
                "reason": "TikTok API not configured. Set TIKTOK_CLIENT_KEY + "
                          "TIKTOK_CLIENT_SECRET in .env. Get them from "
                          "https://developers.tiktok.com/."}
    # TikTok's Content Posting API requires OAuth + a multi-step upload
    # (initialize → upload parts → finalize → publish). This is a stub
    # that documents the flow — full implementation requires the user's
    # OAuth token which we'd cache like the YouTube token.
    return {"success": False,
            "reason": "TikTok upload requires OAuth — connect your TikTok "
                      "account first (similar to YouTube OAuth flow)."}


# ----------------------------------------------------- Instagram upload

async def upload_to_instagram(video_path: str, caption: str,
                               access_token: str | None = None) -> dict:
    """Upload a Reel to Instagram via the Graph API.

    Requires INSTAGRAM_ACCESS_TOKEN in .env (long-lived token from a
    Facebook Business account linked to an Instagram professional account).
    """
    import os
    token = access_token or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    ig_user_id = os.environ.get("INSTAGRAM_USER_ID", "")
    if not token or not ig_user_id:
        return {"success": False,
                "reason": "Instagram API not configured. Set "
                          "INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_USER_ID in .env. "
                          "Get them from https://developers.facebook.com/."}
    # Instagram Graph API Reels upload:
    # 1. POST /{ig_user_id}/media with media_type=REELS + video_url
    # 2. POST /{ig_user_id}/media_publish with creation_id
    # This requires the video to be publicly accessible (URL), so we can't
    # upload a local file directly. The user would need to host it.
    return {"success": False,
            "reason": "Instagram upload requires the video to be publicly "
                      "accessible via URL. Upload to a CDN first, then use "
                      "the Graph API to publish as a Reel."}


# ----------------------------------------------------- Facebook upload

async def upload_to_facebook(video_path: str, description: str,
                              access_token: str | None = None) -> dict:
    """Upload a video to Facebook via the Graph API."""
    import os
    token = access_token or os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
    page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
    if not token or not page_id:
        return {"success": False,
                "reason": "Facebook API not configured. Set "
                          "FACEBOOK_ACCESS_TOKEN + FACEBOOK_PAGE_ID in .env."}
    return {"success": False,
            "reason": "Facebook video upload requires multipart form data "
                      "to the Graph API. Implementation pending — use the "
                      "auto-reframed video + upload manually via Facebook Studio."}


# ----------------------------------------------------- per-platform best time

def get_platform_best_times(platform: str) -> list[dict]:
    """Return the best posting times for a platform (industry averages).

    These are general best-practice times — override with real analytics
    when available.
    """
    times = {
        "youtube": [{"day": "Saturday", "hour": 10}, {"day": "Sunday", "hour": 10},
                    {"day": "Thursday", "hour": 14}, {"day": "Friday", "hour": 15}],
        "tiktok": [{"day": "Tuesday", "hour": 9}, {"day": "Thursday", "hour": 12},
                   {"day": "Friday", "hour": 5}, {"day": "Saturday", "hour": 11}],
        "instagram": [{"day": "Monday", "hour": 11}, {"day": "Tuesday", "hour": 13},
                      {"day": "Wednesday", "hour": 15}, {"day": "Friday", "hour": 10}],
        "facebook": [{"day": "Tuesday", "hour": 9}, {"day": "Wednesday", "hour": 13},
                     {"day": "Thursday", "hour": 14}, {"day": "Friday", "hour": 10}],
        "twitter": [{"day": "Wednesday", "hour": 9}, {"day": "Thursday", "hour": 10},
                    {"day": "Friday", "hour": 9}, {"day": "Tuesday", "hour": 9}],
        "linkedin": [{"day": "Tuesday", "hour": 8}, {"day": "Wednesday", "hour": 10},
                     {"day": "Thursday", "hour": 9}, {"day": "Tuesday", "hour": 12}],
    }
    return times.get(platform, times["youtube"])
