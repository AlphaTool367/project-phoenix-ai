"""Video library + production triggers."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..pipeline.orchestrator import RENDER_PROGRESS, produce_video
from ..schemas import ProduceRequest, VideoDetail, VideoOut
from .deps import get_db

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=list[VideoOut])
def list_videos(channel_id: int | None = None, status: str | None = None,
                limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Video).order_by(Video.id.desc())
    if channel_id:
        q = q.filter(Video.channel_id == channel_id)
    if status:
        q = q.filter(Video.status == status)
    return q.limit(min(limit, 500)).all()


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    return v


@router.get("/{video_id}/progress")
def video_progress(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    return {"status": v.status, "render": RENDER_PROGRESS.get(video_id)}


@router.post("/produce", status_code=202)
async def produce(body: ProduceRequest, background: BackgroundTasks,
                  db: Session = Depends(get_db)):
    if not db.get(Channel, body.channel_id):
        raise HTTPException(404, "channel not found")
    # Apply optional size / aspect / length overrides at runtime.
    if body.resolution or body.aspect or body.target_seconds:
        from ..config import settings
        settings.set_video_options(
            resolution=body.resolution,
            aspect=body.aspect,
            target_seconds=body.target_seconds,
        )
    # run in the app event loop so progress stays visible to the dashboard
    task = asyncio.create_task(produce_video(
        body.channel_id,
        topic=body.topic,
        publish=body.publish,
        scheduled_at=body.scheduled_at,
        target_seconds=body.target_seconds,
        categories=body.categories,
        language_override=body.language,
        show_captions=body.show_captions,
        show_watermark=body.show_watermark,
        show_subscribe_endcard=body.show_subscribe_endcard,
        show_subscribe_badge=body.show_subscribe_badge,
        youtube_category_id=body.youtube_category_id,
        length_mode=body.length_mode,
        clip_shorts=body.clip_shorts,
        scene_count=body.scene_count,
        content_type=body.content_type,
    ))
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return {"started": True, "channel_id": body.channel_id, "topic": body.topic,
            "resolution": __import__("app.config", fromlist=["settings"]).settings.resolution_label}


# ----------------------------------------------------- v1.4 monetization endpoints
@router.get("/{video_id}/shorts")
def list_shorts(video_id: int, db: Session = Depends(get_db)):
    """List all Shorts clipped from a long video."""
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    shorts = db.query(Video).filter_by(parent_video_id=video_id, is_short=True).all()
    return [
        {"id": s.id, "topic": s.topic, "file_path": s.file_path,
         "duration_seconds": s.duration_seconds, "status": s.status}
        for s in shorts
    ]


@router.post("/{video_id}/clip-shorts", status_code=202)
async def clip_shorts_now(video_id: int, db: Session = Depends(get_db)):
    """Manually trigger Shorts clipping on a finished long video."""
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    if not v.file_path or not Path(v.file_path).exists():
        raise HTTPException(400, "video file not rendered yet")
    if v.duration_seconds < 60:
        raise HTTPException(400, "video too short to clip Shorts from (<60s)")

    async def _run():
        from ..services import shorts_clipper as sc
        # Reconstruct scene starts from script_json if present.
        script = v.script_json or {}
        scenes = script.get("scenes") or []
        ss_starts, ss_vdurs = [], []
        cursor = 0.0
        for sc in scenes:
            ss_starts.append(cursor)
            ss_vdurs.append(sc.get("voice_duration", 3.0) if isinstance(sc, dict) else 3.0)
            cursor += (sc.get("voice_duration", 3.0) if isinstance(sc, dict) else 3.0) + 0.45
        from ..config import settings as _s
        shorts_meta = await sc.generate_shorts_from_long(
            parent_video_id=video_id,
            parent_video_path=v.file_path,
            scene_starts=ss_starts,
            voice_durations=ss_vdurs,
            count=_s.shorts_per_long,
        )
        if shorts_meta:
            with __import__("app.database", fromlist=["session_scope"]).session_scope() as sdb:
                for i, sm in enumerate(shorts_meta):
                    short_v = Video(
                        channel_id=v.channel_id,
                        topic=f"{v.topic} — Short {i + 1}",
                        niche=v.niche,
                        language=v.language,
                        status="short_ready",
                        parent_video_id=video_id,
                        is_short=True,
                        file_path=sm["path"],
                        duration_seconds=sm["duration"],
                        categories=v.categories or [],
                    )
                    sdb.add(short_v)

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return {"started": True, "video_id": video_id,
            "shorts_target": __import__("app.config", fromlist=["settings"]).settings.shorts_per_long}


@router.post("/{video_id}/retry", status_code=202)
async def retry_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    v.status = "planned"
    v.error = None
    db.commit()
    task = asyncio.create_task(produce_video(v.channel_id, video_id=v.id))
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return {"restarted": True, "video_id": video_id}


@router.post("/{video_id}/cancel")
def cancel_video(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    if v.status in ("published", "scheduled"):
        raise HTTPException(400, "cannot cancel a published/scheduled video")
    v.status = "cancelled"
    db.commit()
    return {"cancelled": True}


@router.get("/{video_id}/thumbnail/{variant}")
def get_thumbnail(video_id: int, variant: int = 0, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    thumbs = v.thumbnail_variants or ([v.thumbnail_path] if v.thumbnail_path else [])
    if variant >= len(thumbs) or not thumbs[variant] or not Path(thumbs[variant]).exists():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(thumbs[variant])


@router.get("/{video_id}/file")
def get_video_file(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v or not v.file_path or not Path(v.file_path).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(v.file_path, media_type="video/mp4",
                        filename=f"phoenix_v{video_id}.mp4")
