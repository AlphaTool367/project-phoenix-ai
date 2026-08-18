"""Growth endpoints — competitor monitoring + A/B testing + smart re-upload."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..services import growth
from .deps import get_db

router = APIRouter(prefix="/api/growth", tags=["growth"])


# ----------------------------------------------------- competitors

class CompetitorAdd(BaseModel):
    yt_channel_id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=120)


@router.get("/competitors/{channel_id}")
def list_competitors(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return growth.list_competitors(channel_id)


@router.post("/competitors/{channel_id}")
def add_competitor(channel_id: int, body: CompetitorAdd,
                   db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return growth.add_competitor(channel_id, body.yt_channel_id, body.label)


@router.delete("/competitors/{channel_id}/{competitor_id}")
def remove_competitor(channel_id: int, competitor_id: int,
                      db: Session = Depends(get_db)):
    return growth.remove_competitor(channel_id, competitor_id)


@router.post("/competitors/{channel_id}/{competitor_id}/sync")
def sync_competitor(channel_id: int, competitor_id: int,
                    db: Session = Depends(get_db)):
    return growth.sync_competitor_videos(channel_id, competitor_id)


@router.get("/competitors/{channel_id}/{competitor_id}/videos")
def competitor_videos(channel_id: int, competitor_id: int,
                      limit: int = 20, db: Session = Depends(get_db)):
    return growth.list_competitor_videos(competitor_id, limit=limit)


# ----------------------------------------------------- A/B testing

@router.post("/ab-test/{video_id}/titles")
async def suggest_titles(video_id: int, count: int = 3,
                          db: Session = Depends(get_db)):
    """Suggest alternative titles for A/B testing."""
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    titles = await growth.suggest_title_alternatives(v, count=count)
    return {"current_title": v.title, "alternatives": titles}


# ----------------------------------------------------- smart re-upload

@router.get("/underperforming/{channel_id}")
def underperforming(channel_id: int, days: int = 14,
                    threshold_pct: float = 0.5,
                    db: Session = Depends(get_db)):
    """Find videos that underperformed the channel average."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return growth.find_underperforming_videos(channel_id, days=days,
                                               threshold_pct=threshold_pct)


@router.post("/underperforming/{video_id}/suggest")
async def suggest_overhaul(video_id: int, db: Session = Depends(get_db)):
    """Suggest new title + tags + description for an underperforming video."""
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    return await growth.suggest_metadata_overhaul(v)


class MetadataUpdate(BaseModel):
    video_yt_id: str
    title: str
    description: str
    tags: list[str]


@router.post("/underperforming/{channel_id}/apply")
def apply_overhaul(channel_id: int, body: MetadataUpdate,
                   db: Session = Depends(get_db)):
    """Apply the metadata overhaul to a published video via YouTube API."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return growth.apply_metadata_update(
        channel_id, body.video_yt_id, body.title, body.description, body.tags)
