"""AI Helpers — comment replies, thumbnail feedback, script editor, fact-check.

  - Auto-reply to comments: LLM generates a relevant reply to each comment.
  - AI thumbnail feedback: LLM analyzes a thumbnail image and scores it.
  - AI script editor: LLM suggests improvements to a video script.
  - Fact-checking: Google Fact Check API to verify claims.
"""
from __future__ import annotations

from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("ai_helpers")


# ----------------------------------------------------- auto-reply to comments

async def generate_comment_reply(comment_text: str, video_topic: str) -> str:
    """Generate a relevant reply to a YouTube comment via LLM."""
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube creator replying to comments on your video. "
            "Write a short, genuine reply (≤200 chars) that acknowledges the "
            "commenter and adds value. Be friendly, not robotic. No hashtags."
        )},
        {"role": "user", "content": (
            f"Video topic: {video_topic}\n\n"
            f"Comment: \"{comment_text}\"\n\nReply:"
        )},
    ]
    text = await llm.chat(prompt, temperature=0.7)
    return clamp(text or "Thanks for watching!", 200)


async def auto_reply_to_comments(video_id: int, max_replies: int = 5) -> dict:
    """Fetch recent comments on a video + generate replies for each."""
    from ..database import session_scope
    from ..models import Video
    from .uploader import _youtube_client
    with session_scope() as db:
        v = db.get(Video, video_id)
        if not v or not v.yt_video_id or v.yt_video_id.startswith("DRYRUN"):
            return {"available": False, "reason": "video not published"}
        channel_id = v.channel_id
        yt_id = v.yt_video_id
        topic = v.topic
    yt = _youtube_client(channel_id)
    if yt is None:
        return {"available": False, "reason": "YouTube not connected"}
    try:
        resp = yt.commentThreads().list(
            part="snippet", videoId=yt_id, maxResults=max_replies,
            order="time",
        ).execute()
        replies = []
        for item in resp.get("items", []):
            comment_id = (item.get("snippet", {}).get("topLevelComment", {})
                          .get("id"))
            comment_text = (item.get("snippet", {}).get("topLevelComment", {})
                            .get("snippet", {}).get("textOriginal", ""))
            if not comment_text:
                continue
            reply_text = await generate_comment_reply(comment_text, topic)
            replies.append({
                "comment_id": comment_id,
                "original_comment": comment_text[:100],
                "suggested_reply": reply_text,
            })
        return {"available": True, "replies": replies, "count": len(replies)}
    except Exception as exc:
        log.warning("auto-reply failed: %s", exc)
        return {"available": False, "reason": str(exc)}


# ----------------------------------------------------- thumbnail feedback

async def analyze_thumbnail(thumbnail_path: str, video_title: str) -> dict:
    """Ask the LLM to give feedback on a thumbnail.

    NOTE: Without a vision model (GPT-4V), we can only analyze the
    thumbnail's metadata (dimensions, colors, file size). The LLM can
    give general advice based on the title + niche.
    """
    from PIL import Image
    from pathlib import Path
    p = Path(thumbnail_path)
    if not p.exists():
        return {"available": False, "reason": "thumbnail not found"}
    try:
        img = Image.open(p)
        w, h = img.size
        # Get dominant colors.
        colors = img.convert("RGB").getcolors(maxcolors=256)
        dominant = max(colors, key=lambda c: c[0])[1] if colors else (0, 0, 0)
    except Exception:
        w, h, dominant = 0, 0, (0, 0, 0)
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube thumbnail CTR expert. The user has described "
            "a thumbnail (dimensions + dominant color + video title). Give "
            "feedback on how to improve it. Respond ONLY with JSON: "
            "{score: 0-100, strengths: [str], weaknesses: [str], suggestions: [str]}."
        )},
        {"role": "user", "content": (
            f"Title: {video_title}\n"
            f"Thumbnail dimensions: {w}x{h}\n"
            f"Dominant color: RGB{dominant}\n"
            f"File size: {p.stat().st_size // 1024} KB"
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.4)
    if isinstance(data, dict):
        return {"available": True, **data, "dimensions": f"{w}x{h}"}
    return {"available": True, "score": 50,
            "strengths": [], "weaknesses": ["unable to analyze"],
            "suggestions": ["try regenerating the thumbnail"],
            "dimensions": f"{w}x{h}"}


# ----------------------------------------------------- script editor

async def suggest_script_improvements(script: dict) -> dict:
    """Analyze a video script and suggest improvements."""
    scenes = script.get("scenes", [])
    narration = "\n".join(f"Scene {i+1} ({s.get('beat', '')}): {s.get('narration', '')}"
                          for i, s in enumerate(scenes))
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube script editor. Analyze the script and suggest "
            "improvements for retention, clarity, pacing, and emotional arc. "
            "Respond ONLY with JSON: {overall_score: 0-100, strengths: [str], "
            "weaknesses: [str], scene_suggestions: [{scene_index, suggestion}]}."
        )},
        {"role": "user", "content": (
            f"Topic: {script.get('topic', '')}\n"
            f"Niche: {script.get('niche', '')}\n\nScript:\n{narration}"
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.5)
    if isinstance(data, dict):
        return data
    return {"overall_score": 60, "strengths": [], "weaknesses": [],
            "scene_suggestions": []}


# ----------------------------------------------------- fact-checking

async def fact_check_claim(claim: str) -> dict:
    """Check a factual claim using the Google Fact Check API (free)."""
    import httpx
    api_key = settings.fpcalc_path  # reuse — actually need a Google Fact Check key
    # Google Fact Check API: https://factchecktools.googleapis.com/v1alpha/claims:search
    # Requires a Google API key with Fact Check Tools API enabled.
    import os
    google_api_key = os.environ.get("GOOGLE_FACT_CHECK_API_KEY", "")
    if not google_api_key:
        return {"available": False,
                "reason": "GOOGLE_FACT_CHECK_API_KEY not set. Enable the "
                          "Fact Check Tools API in Google Cloud Console."}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://factchecktools.googleapis.com/v1alpha/claims:search",
                params={"query": claim, "key": google_api_key, "languageCode": "en"},
            )
        if r.status_code != 200:
            return {"available": False, "reason": f"API returned {r.status_code}"}
        data = r.json()
        claims = data.get("claims", [])
        if not claims:
            return {"available": True, "found": False, "claim": claim,
                    "reason": "no fact checks found for this claim"}
        results = []
        for c in claims[:5]:
            results.append({
                "text": c.get("text", "")[:200],
                "claimant": c.get("claimant", ""),
                "rating": (c.get("claimReview", [{}])[0].get("textualRating", "")
                           if c.get("claimReview") else ""),
                "publisher": (c.get("claimReview", [{}])[0].get("publisher", {})
                              .get("name", "") if c.get("claimReview") else ""),
                "url": (c.get("claimReview", [{}])[0].get("url", "")
                        if c.get("claimReview") else ""),
            })
        return {"available": True, "found": True, "claim": claim,
                "checks": results}
    except Exception as exc:
        log.warning("fact check failed: %s", exc)
        return {"available": False, "reason": str(exc)}
