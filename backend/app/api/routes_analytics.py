"""Analytics endpoints + manual sync/learning triggers.

Real-time channel overview: returns live YouTube subscriber / view / video
counts + the local rollup of per-video analytics. Used by the dashboard
header so the user sees fresh numbers right after OAuth.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import AnalyticsSnapshot, Channel, Video
from ..services import analytics, learning
from .deps import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/channel/{channel_id}")
async def channel_analytics(channel_id: int):
    return await analytics.channel_summary(channel_id)


@router.get("/channel/{channel_id}/realtime")
async def channel_realtime(channel_id: int, db: Session = Depends(get_db)):
    """Live YouTube channel stats + local analytics rollup."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return await analytics.realtime_channel_overview(channel_id)


@router.get("/channel/{channel_id}/timeseries")
async def channel_timeseries(channel_id: int, db: Session = Depends(get_db)):
    snaps = (
        db.query(AnalyticsSnapshot)
        .filter(AnalyticsSnapshot.channel_id == channel_id)
        .order_by(AnalyticsSnapshot.captured_at)
        .all()
    )
    return [
        {"ts": s.captured_at.isoformat(), "video_id": s.video_id,
         "views": s.views, "retention_pct": s.retention_pct,
         "ctr_pct": s.ctr_pct, "subs_gained": s.subs_gained}
        for s in snaps
    ]


@router.get("/video/{video_id}")
async def video_analytics(video_id: int, db: Session = Depends(get_db)):
    snaps = (
        db.query(AnalyticsSnapshot)
        .filter(AnalyticsSnapshot.video_id == video_id)
        .order_by(AnalyticsSnapshot.captured_at)
        .all()
    )
    return [
        {"ts": s.captured_at.isoformat(), "views": s.views,
         "watch_minutes": s.watch_minutes, "retention_pct": s.retention_pct,
         "ctr_pct": s.ctr_pct, "likes": s.likes, "comments": s.comments,
         "shares": s.shares, "subs_gained": s.subs_gained, "source": s.source}
        for s in snaps
    ]


@router.get("/leaderboard/{channel_id}")
async def leaderboard(channel_id: int, db: Session = Depends(get_db)):
    """Latest snapshot per video joined with titles, ranked by views."""
    snaps = (
        db.query(AnalyticsSnapshot, Video)
        .join(Video, Video.id == AnalyticsSnapshot.video_id)
        .filter(AnalyticsSnapshot.channel_id == channel_id)
        .order_by(AnalyticsSnapshot.captured_at.desc())
        .all()
    )
    seen: dict[int, dict] = {}
    for s, v in snaps:
        if v.id in seen:
            continue
        seen[v.id] = {
            "video_id": v.id, "title": v.title or v.topic,
            "views": s.views, "retention_pct": s.retention_pct,
            "ctr_pct": s.ctr_pct, "subs_gained": s.subs_gained,
        }
    return sorted(seen.values(), key=lambda r: r["views"], reverse=True)


@router.post("/sync/{channel_id}")
async def sync_now(channel_id: int):
    try:
        count = await analytics.sync_channel_analytics(channel_id)
        return {"synced": count}
    except Exception as exc:
        raise HTTPException(500, f"sync failed: {exc}") from exc


@router.post("/learn/{channel_id}")
async def learn_now(channel_id: int):
    return await learning.update_strategy(channel_id)
