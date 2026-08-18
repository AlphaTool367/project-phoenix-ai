"""Routes for all v1.9 medium-difficulty features."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..services import (ai_helpers, analytics_deep, compilations_bot,
                        editor_pro, platform_upload, voice_translate)
from .deps import get_db

router = APIRouter(prefix="/api/v19", tags=["v1.9"])


# ----------------------------------------------------- editor pro

@router.get("/editor/gpu-available")
def gpu_available():
    enc = editor_pro.gpu_encoder_available()
    return {"available": enc is not None, "encoder": enc}


@router.post("/editor/intro")
async def gen_intro(channel_name: str = "Phoenix AI", duration: float = 3.0):
    from pathlib import Path
    out = Path("data/assets/intro.mp4")
    path = await editor_pro.generate_intro(channel_name, out, duration)
    return {"path": path, "duration": duration}


@router.post("/editor/outro")
async def gen_outro(channel_name: str = "Phoenix AI", duration: float = 4.0):
    from pathlib import Path
    out = Path("data/assets/outro.mp4")
    path = await editor_pro.generate_outro(channel_name, out, duration)
    return {"path": path, "duration": duration}


@router.post("/editor/split-screen")
async def split_screen(clip_a: str, clip_b: str, layout: str = "side_by_side"):
    from pathlib import Path
    out = Path("data/output/split_screen.mp4")
    path = await editor_pro.create_split_screen(clip_a, clip_b, out, layout)
    return {"path": path, "layout": layout}


@router.post("/editor/carousel/{video_id}")
async def carousel(video_id: int, scene_count: int = 5,
                    db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v or not v.file_path:
        raise HTTPException(400, "video not found or no file")
    paths = await editor_pro.video_to_instagram_carousel(
        v.file_path, scene_count)
    return {"images": paths, "count": len(paths)}


# ----------------------------------------------------- voice & translation

@router.get("/voice/emotions")
def list_emotions():
    return {"emotions": list(voice_translate.EMOTION_PRESETS.keys())}


@router.post("/voice/auto-dub/{video_id}")
async def auto_dub(video_id: int, target_language: str,
                    db: Session = Depends(get_db)):
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    result = await voice_translate.auto_dub_video(video_id, target_language)
    return result


@router.post("/voice/remove-bg")
async def remove_bg(image_path: str):
    result = await voice_translate.remove_background_from_image(image_path)
    return result


# ----------------------------------------------------- platform upload

@router.post("/platform/reframe")
async def reframe(video_path: str, target_aspect: str = "portrait"):
    result = await platform_upload.auto_reframe(video_path, target_aspect)
    return result


@router.post("/platform/reframe-all")
async def reframe_all(video_path: str):
    return await platform_upload.reframe_for_all_platforms(video_path)


@router.post("/platform/tiktok")
async def tiktok_upload(video_path: str, title: str, hashtags: str = ""):
    return await platform_upload.upload_to_tiktok(
        video_path, title, hashtags.split(",") if hashtags else [])


@router.post("/platform/instagram")
async def instagram_upload(video_path: str, caption: str):
    return await platform_upload.upload_to_instagram(video_path, caption)


@router.get("/platform/best-times/{platform}")
def best_times(platform: str):
    return {"times": platform_upload.get_platform_best_times(platform)}


# ----------------------------------------------------- analytics deep

@router.get("/analytics/realtime-subs/{channel_id}")
def realtime_subs(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_deep.get_realtime_subscribers(channel_id)


@router.get("/analytics/retention/{video_id}")
def retention_heatmap(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v or not v.yt_video_id:
        raise HTTPException(404, "video not found")
    return analytics_deep.fetch_retention_heatmap(v.yt_video_id, v.channel_id)


@router.get("/analytics/predict/{video_id}")
def predict_views(video_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    return analytics_deep.predict_video_views(video_id, days)


@router.post("/analytics/pdf-report/{channel_id}")
def pdf_report(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_deep.generate_pdf_report(channel_id, days)


@router.get("/analytics/funnel/{channel_id}")
def funnel(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_deep.get_funnel_analysis(channel_id, days)


# ----------------------------------------------------- AI helpers

@router.post("/ai/comment-replies/{video_id}")
async def comment_replies(video_id: int, max_replies: int = 5,
                           db: Session = Depends(get_db)):
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    return await ai_helpers.auto_reply_to_comments(video_id, max_replies)


@router.post("/ai/thumbnail-feedback")
async def thumbnail_feedback(thumbnail_path: str, video_title: str = ""):
    return await ai_helpers.analyze_thumbnail(thumbnail_path, video_title)


@router.post("/ai/script-edit/{video_id}")
async def script_edit(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    return await ai_helpers.suggest_script_improvements(v.script_json or {})


@router.post("/ai/fact-check")
async def fact_check(claim: str):
    return await ai_helpers.fact_check_claim(claim)


# ----------------------------------------------------- compilations & bot

@router.post("/compilations/best-of/{channel_id}")
async def best_of(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return await compilations_bot.generate_best_of_compilation(channel_id, days)


@router.post("/compilations/year-review/{channel_id}")
async def year_review(channel_id: int, year: int | None = None,
                       db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return await compilations_bot.generate_year_in_review(channel_id, year)


@router.post("/compilations/trailer/{channel_id}")
async def trailer(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return await compilations_bot.generate_channel_trailer(channel_id)


@router.get("/telegram/status")
def telegram_status():
    return {"available": compilations_bot.telegram_bot_available(),
            "instructions": compilations_bot.get_telegram_bot_instructions()}


@router.post("/telegram/start")
async def telegram_start():
    return await compilations_bot.start_telegram_bot()
