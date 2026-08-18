"""Auto-upload helper — generates tags/title/description + uploads any video.

When a cartoon Short or AI story video is generated, this module:
  1. Asks the LLM to generate a title (≤95 chars, click-worthy)
  2. Asks the LLM to generate tags (≤14, SEO-optimized)
  3. Asks the LLM to generate a description (with chapters + CTA)
  4. Creates a Video row in the DB
  5. Uploads to YouTube with auto-generated metadata
  6. Runs copyright check → auto-publish/delete

This makes the full flow hands-free: download cartoon → clip → upload.
Or: generate AI story → upload. No manual step needed.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..core.logging import get_logger
from ..core.utils import clamp
from ..database import session_scope
from ..models import Video
from . import compliance, llm, quality, seo, uploader

log = get_logger("auto_upload")


async def generate_metadata(topic: str, niche: str, language: str = "en",
                             video_type: str = "short") -> dict:
    """Generate title + description + tags + hashtags for a video via LLM.

    Args:
        topic: What the video is about.
        niche: The niche/category.
        language: SEO language (always English for max reach).
        video_type: 'short' or 'long' — affects title style.

    Returns:
        {title, description, tags, hashtags}
    """
    style_guides = {
        "short": "punchy, curiosity-driven, ≤95 chars, optimized for Shorts/Reels/TikTok",
        "long": "keyword front-loaded, ≤95 chars, optimized for YouTube search",
    }
    style_guide = style_guides.get(video_type, style_guides["short"])

    prompt = [
        {"role": "system", "content": (
            f"You are a YouTube SEO expert. Generate metadata for a {video_type} video. "
            f"Title: {style_guide}. Description: 2 short paragraphs + CTA, ≤3000 chars. "
            f"Tags: ≤14 lowercase keywords. Hashtags: ≤3 with #. "
            f"All text in {language}. Respond ONLY with JSON: "
            f"{{title, description, tags (array), hashtags (array)}}."
        )},
        {"role": "user", "content": f"Topic: {topic}\nNiche: {niche}"},
    ]
    data = await llm.chat_json(prompt, temperature=0.7)
    if isinstance(data, dict) and data.get("title"):
        return {
            "title": clamp(str(data["title"]), 95),
            "description": clamp(str(data.get("description", "")), 4500),
            "tags": [str(t) for t in data.get("tags", [])][:14],
            "hashtags": [str(h) for h in data.get("hashtags", [])][:3],
        }
    # Fallback.
    return {
        "title": clamp(f"{topic} — You Won't Believe What Happens Next", 95),
        "description": f"Watch this amazing video about {topic}!\n\nSubscribe for more!",
        "tags": [niche, topic.lower().split()[0] if topic else "video",
                 "shorts", "viral", "2026"],
        "hashtags": [f"#{niche}", "#shorts", "#viral"],
    }


async def auto_upload_video(
    file_path: str,
    channel_id: int,
    topic: str,
    niche: str = "entertainment",
    language: str = "en",
    is_short: bool = True,
    youtube_category_id: str = "24",  # 24 = Entertainment (good for cartoons)
    auto_publish: bool = True,
) -> dict:
    """Full auto-upload flow: generate metadata → create Video row → upload.

    This is the hands-free function. Give it a video file path + topic,
    and it handles everything: title, tags, description, upload, copyright
    check, auto-publish.

    Returns:
        {success, video_id, yt_video_id, title, url}
    """
    if not Path(file_path).exists():
        return {"success": False, "reason": "video file not found"}

    # Step 1: generate metadata.
    log.info("auto-upload: generating metadata for '%s'", topic[:50])
    meta = await generate_metadata(topic, niche, language,
                                    "short" if is_short else "long")
    log.info("auto-upload: title='%s', tags=%d", meta["title"], len(meta["tags"]))

    # Step 2: create a Video row.
    from ..core.utils import probe_duration
    duration = await probe_duration(file_path) or 60.0
    with session_scope() as db:
        v = Video(
            channel_id=channel_id,
            topic=topic,
            niche=niche,
            title=meta["title"],
            description=meta["description"],
            tags=meta["tags"],
            hashtags=meta["hashtags"],
            language=language,
            status="rendered",
            file_path=file_path,
            duration_seconds=duration,
            is_short=is_short,
            categories=[niche],
            strategy_context={"source": "special_flow", "auto_upload": True},
        )
        db.add(v)
        db.flush()
        video_id = v.id
    log.info("auto-upload: created video #%d", video_id)

    # Step 3: automatic artifact quality gate before any upload.
    quality_report = await quality.inspect_rendered_video(
        file_path, duration, script=None,
    )
    with session_scope() as db:
        v = db.get(Video, video_id)
        if v:
            seo_json = v.seo_json or {}
            seo_json["quality_report"] = quality_report
            v.seo_json = seo_json
    if not quality_report.get("passed"):
        reason = "; ".join(quality_report.get("critical_errors", []))
        with session_scope() as db:
            v = db.get(Video, video_id)
            if v:
                v.status = "failed"
                v.error = f"Automatic quality block: {reason}"[:2000]
        log.warning("auto-upload blocked by quality for video #%d: %s", video_id, reason)
        return {"success": False, "video_id": video_id, "blocked": True,
                "reason": f"Automatic quality block: {reason}",
                "quality": quality_report}

    # Step 4: automatic compliance gate before any upload.
    try:
        compliance_report = await compliance.score_compliance(
            topic=topic, niche=niche, title=meta["title"],
            description=meta["description"], narration="",
        )
        with session_scope() as db:
            v = db.get(Video, video_id)
            if v:
                seo_json = v.seo_json or {}
                seo_json["compliance_report"] = compliance_report
                v.seo_json = seo_json
        recommendation = compliance_report.get("recommendation")
        if recommendation in {"do_not_publish", "review_manually"}:
            reason = "; ".join(compliance_report.get("reasons", [])) or recommendation
            with session_scope() as db:
                v = db.get(Video, video_id)
                if v:
                    v.status = "failed"
                    v.error = f"Automatic safety block: {reason}"[:2000]
            log.warning("auto-upload blocked by compliance for video #%d: %s", video_id, reason)
            return {
                "success": False, "video_id": video_id, "title": meta["title"],
                "blocked": True, "reason": f"Automatic safety block: {reason}",
                "compliance": compliance_report,
            }
    except Exception as exc:
        log.warning("auto-upload compliance check failed; blocking for safety: %s", exc)
        with session_scope() as db:
            v = db.get(Video, video_id)
            if v:
                v.status = "failed"
                v.error = f"Automatic safety check unavailable: {exc}"[:2000]
        return {"success": False, "video_id": video_id,
                "blocked": True, "reason": f"Automatic safety check unavailable: {exc}"}

    # Step 5: upload to YouTube.
    if not auto_publish:
        return {"success": True, "video_id": video_id,
                "title": meta["title"], "uploaded": False}

    from ..config import settings
    # Safety Pack gate: special flows must not bypass human approval.
    if (settings.approval_required and not settings.youtube_dry_run
            and not settings.force_mock_youtube):
        with session_scope() as db:
            v = db.get(Video, video_id)
            if v:
                v.status = "awaiting_review"
                v.review_status = "pending"
                v.review_notes = "Awaiting human approval before live upload."
        log.warning("auto-upload blocked for video #%d: approval required", video_id)
        return {"success": True, "video_id": video_id, "title": meta["title"],
                "uploaded": False, "awaiting_review": True,
                "reason": "Human approval is required before live upload."}

    with session_scope() as db:
        v = db.get(Video, video_id)
        setattr(v, "_yt_category_id", youtube_category_id)
        try:
            result = await uploader.upload_video(v, channel_id)
        except Exception as exc:
            log.error("auto-upload: upload failed: %s", exc)
            return {"success": False, "video_id": video_id,
                    "reason": f"upload failed: {exc}"}

    yt_id = result.get("yt_video_id", "")
    is_dry = result.get("dry_run", False)

    if is_dry or not yt_id or yt_id.startswith("DRYRUN"):
        log.info("auto-upload: dry-run (no real upload)")
        with session_scope() as db:
            v = db.get(Video, video_id)
            v.status = "published"
            v.yt_video_id = yt_id
            v.published_at = datetime.utcnow()
        return {"success": True, "video_id": video_id,
                "yt_video_id": yt_id, "title": meta["title"],
                "dry_run": True}

    # Step 6: copyright check + auto-publish.
    from ..config import settings
    if settings.copyright_check_enabled:
        log.info("auto-upload: running copyright check on %s", yt_id)
        with session_scope() as db:
            v = db.get(Video, video_id)
            v.status = "checking"
            v.yt_video_id = yt_id
        try:
            cr = await uploader.copyright_check_and_finalize(
                channel_id, yt_id, video_id=video_id)
            log.info("auto-upload: copyright result: %s", cr.get("action"))
        except Exception as exc:
            log.error("auto-upload: copyright check failed: %s", exc)
    else:
        with session_scope() as db:
            v = db.get(Video, video_id)
            v.status = "published"
            v.yt_video_id = yt_id
            v.published_at = datetime.utcnow()

    return {
        "success": True,
        "video_id": video_id,
        "yt_video_id": yt_id,
        "title": meta["title"],
        "tags": meta["tags"],
        "description": meta["description"][:200],
        "url": f"https://youtu.be/{yt_id}" if yt_id and not yt_id.startswith("DRYRUN") else None,
        "dry_run": is_dry,
    }


async def auto_upload_cartoon_shorts(
    shorts: list[dict],
    channel_id: int,
    niche: str = "entertainment",
    language: str = "en",
    youtube_category_id: str = "24",
) -> list[dict]:
    """Upload all cartoon Shorts automatically.

    Each Short gets:
      - Auto-generated title (e.g. "Hilarious Cartoon Moment You Can't Miss! 😂")
      - Auto-generated tags (cartoon, funny, shorts, viral, etc.)
      - Auto-generated description
      - YouTube upload
      - Copyright check
      - Auto-publish if clean
    """
    results = []
    for i, s in enumerate(shorts):
        if not s.get("clean", True):
            log.warning("auto-upload: skipping Short %d (copyright flagged)", i + 1)
            results.append({"index": i + 1, "skipped": True,
                            "reason": "copyright flagged"})
            continue
        topic = f"Cartoon Short {i+1} — Funny Moment"
        result = await auto_upload_video(
            file_path=s["path"],
            channel_id=channel_id,
            topic=topic,
            niche=niche,
            language=language,
            is_short=True,
            youtube_category_id=youtube_category_id,
            auto_publish=True,
        )
        result["index"] = i + 1
        results.append(result)
    return results


async def upload_existing_approved_video(
    video_id: int,
    channel_id: int,
    youtube_category_id: str = "24",
) -> dict:
    """Upload a rendered special-flow Video after explicit approval.

    This deliberately operates on the existing rendered file instead of
    sending the row back through the normal orchestrator, which would create
    a second story/cartoon render because these flows do not have a script
    checkpoint in the standard pipeline.
    """
    from ..config import settings

    with session_scope() as db:
        video = db.get(Video, video_id)
        if not video or not video.file_path or not Path(video.file_path).exists():
            return {"success": False, "reason": "approved video file not found", "video_id": video_id}
        setattr(video, "_yt_category_id", youtube_category_id)
        video.status = "uploading"
        result = None
        try:
            result = await uploader.upload_video(video, channel_id)
        except Exception as exc:
            video.status = "failed"
            video.error = f"approved upload failed: {exc}"[:2000]
            return {"success": False, "video_id": video_id, "reason": str(exc)}

    yt_id = result.get("yt_video_id", "") if result else ""
    is_dry = bool(result.get("dry_run")) if result else False
    with session_scope() as db:
        video = db.get(Video, video_id)
        if is_dry or not yt_id or yt_id.startswith("DRYRUN"):
            video.status = "published"
            video.yt_video_id = yt_id
            video.published_at = datetime.utcnow()
        elif settings.copyright_check_enabled:
            video.status = "checking"
            video.yt_video_id = yt_id
        else:
            video.status = "published"
            video.yt_video_id = yt_id
            video.published_at = datetime.utcnow()

    if (not is_dry and yt_id and not yt_id.startswith("DRYRUN")
            and settings.copyright_check_enabled):
        try:
            await uploader.copyright_check_and_finalize(channel_id, yt_id, video_id=video_id)
        except Exception as exc:
            log.error("approved upload copyright check failed: %s", exc)
            with session_scope() as db:
                video = db.get(Video, video_id)
                if video:
                    video.status = "failed"
                    video.error = f"copyright check failed: {exc}"[:2000]
            return {"success": False, "video_id": video_id, "yt_video_id": yt_id,
                    "reason": str(exc)}

    return {
        "success": True,
        "video_id": video_id,
        "yt_video_id": yt_id,
        "dry_run": is_dry,
        "url": f"https://youtu.be/{yt_id}" if yt_id and not yt_id.startswith("DRYRUN") else None,
    }
