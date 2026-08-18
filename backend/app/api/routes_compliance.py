"""Compliance + trend tracker endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..services import compliance, trend_tracker
from .deps import get_db

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.post("/score/{video_id}")
async def score_video(video_id: int, db: Session = Depends(get_db)):
    """Score a video's compliance (ad-friendliness, made-for-kids, etc.)."""
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    result = await compliance.score_compliance(
        topic=v.topic, niche=v.niche,
        title=v.title or v.topic,
        description=v.description or "",
        narration=(v.script_json or {}).get("scenes", [{}])[0].get("narration", "")
        if (v.script_json or {}).get("scenes") else "",
    )
    # Persist on the video.
    seo = v.seo_json or {}
    seo["compliance_report"] = result
    v.seo_json = seo
    db.commit()
    return result


@router.get("/score/{video_id}")
def get_score(video_id: int, db: Session = Depends(get_db)):
    """Return the cached compliance score for a video."""
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    return (v.seo_json or {}).get("compliance_report", {})


# ----- Trend tracker

trend_router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/discover/{channel_id}")
async def discover_trends(channel_id: int, niche: str | None = None,
                           db: Session = Depends(get_db)):
    """Discover trending topics across Google Trends + Reddit + News."""
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    n = niche or ch.niche
    return await trend_tracker.discover_trending_topics(n)


@router.get("/velocity/{topic}")
def trend_velocity(topic: str, niche: str = "technology"):
    """Get a single topic's trend velocity + saturation score."""
    return trend_tracker.get_trend_velocity(topic, niche)


@trend_router.get("/discover/{channel_id}")
async def discover_trends_v2(channel_id: int, niche: str | None = None,
                              db: Session = Depends(get_db)):
    """Discover trending topics across Google Trends + Reddit + News."""
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    n = niche or ch.niche
    return await trend_tracker.discover_trending_topics(n)


@trend_router.get("/velocity/{topic}")
def trend_velocity_v2(topic: str, niche: str = "technology"):
    return trend_tracker.get_trend_velocity(topic, niche)
