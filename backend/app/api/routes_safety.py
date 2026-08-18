"""Production Safety Pack API.

All write actions are explicit and auditable. Restore requires a confirmation
flag, and approval is required before real publishing when enabled.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import session_scope
from ..models import ActivityLog, Channel, Job, ScheduledSlot, Video
from ..pipeline.orchestrator import produce_video
from ..services import provider_usage, safety
from .deps import get_db

router = APIRouter(prefix="/api/safety", tags=["safety-pack"])


class ReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject|reset)$")
    notes: str = Field(default="", max_length=4000)
    reviewer: str = Field(default="dashboard-user", max_length=120)


class RestoreRequest(BaseModel):
    confirm: bool = False


@router.get("/summary")
def safety_summary(db: Session = Depends(get_db)):
    videos = db.query(Video)
    return {
        "approval_required": settings.approval_required,
        "pending_review": videos.filter(Video.review_status == "pending").count(),
        "approved": videos.filter(Video.review_status == "approved").count(),
        "rejected": videos.filter(Video.review_status == "rejected").count(),
        "awaiting_review": videos.filter(Video.status == "awaiting_review").count(),
        "failed_jobs": db.query(Job).filter(Job.status.in_(["failed", "dead"])).count(),
        "backups": len(safety.list_backups()),
        "notifications_enabled": settings.notifications_enabled,
        "quota": safety.quota_status(),
        "provider_usage": provider_usage.summary(1),
    }


@router.get("/provider-usage")
def provider_usage_summary(days: int = 1):
    """Return provider-reported tokens/cost and explicit unknown balances."""
    return provider_usage.summary(days)


@router.get("/review-queue")
def review_queue(channel_id: int | None = None, limit: int = 100,
                 db: Session = Depends(get_db)):
    query = db.query(Video).filter(
        Video.review_status.in_(["pending", "rejected"]),
        Video.status.in_(["rendered", "awaiting_review", "rejected"]),
    ).order_by(Video.updated_at.desc())
    if channel_id is not None:
        query = query.filter(Video.channel_id == channel_id)
    rows = query.limit(max(1, min(limit, 500))).all()
    return [
        {
            "id": v.id,
            "channel_id": v.channel_id,
            "title": v.title or v.topic,
            "topic": v.topic,
            "status": v.status,
            "review_status": v.review_status,
            "review_notes": v.review_notes,
            "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
            "reviewed_by": v.reviewed_by,
            "thumbnail_path": v.thumbnail_path,
            "file_path": v.file_path,
            "scheduled_at": v.scheduled_at.isoformat() if v.scheduled_at else None,
            "hook_score": v.hook_score,
            "copyright_check_passed": v.copyright_check_passed,
            "predicted_ctr": v.predicted_ctr,
            "created_at": v.created_at.isoformat(),
        }
        for v in rows
    ]


@router.post("/review/{video_id}", status_code=202)
async def review_video(video_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "video not found")
    if body.action == "approve":
        if not video.file_path or not Path(video.file_path).exists():
            raise HTTPException(400, "video file must exist before approval")
        video.review_status = "approved"
        video.review_notes = body.notes
        video.reviewed_at = datetime.utcnow()
        video.reviewed_by = body.reviewer
        if video.status in ("awaiting_review", "rejected"):
            video.status = "rendered"
        db.commit()
        safety.record_notification(video.channel_id, "review_approved",
                                   f"Video #{video.id} approved", body.notes,
                                   delivered=False)
        if (video.strategy_context or {}).get("source") == "special_flow":
            from ..services.auto_upload import upload_existing_approved_video
            task = asyncio.create_task(upload_existing_approved_video(
                video_id=video.id,
                channel_id=video.channel_id,
            ))
        else:
            task = asyncio.create_task(produce_video(
                channel_id=video.channel_id,
                video_id=video.id,
                topic=video.topic,
                scheduled_at=video.scheduled_at,
                publish=True,
            ))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return {"accepted": True, "action": "approve", "video_id": video_id,
                "message": "Approval saved; publishing pipeline resumed."}
    if body.action == "reject":
        video.review_status = "rejected"
        video.review_notes = body.notes
        video.reviewed_at = datetime.utcnow()
        video.reviewed_by = body.reviewer
        video.status = "rejected"
        db.commit()
        safety.record_notification(video.channel_id, "review_rejected",
                                   f"Video #{video.id} rejected", body.notes,
                                   delivered=False)
        return {"accepted": True, "action": "reject", "video_id": video_id}

    video.review_status = "pending"
    video.review_notes = body.notes
    video.reviewed_at = None
    video.reviewed_by = None
    if video.status == "rejected":
        video.status = "rendered"
    db.commit()
    return {"accepted": True, "action": "reset", "video_id": video_id}


@router.get("/calendar")
def content_calendar(start: datetime | None = None, days: int = 31,
                    channel_id: int | None = None, db: Session = Depends(get_db)):
    start = start or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=max(1, min(days, 90)))
    query = db.query(Video).filter(
        Video.scheduled_at.is_not(None),
        Video.scheduled_at >= start,
        Video.scheduled_at < end,
    ).order_by(Video.scheduled_at)
    if channel_id is not None:
        query = query.filter(Video.channel_id == channel_id)
    items = [{
        "kind": "video",
        "id": v.id,
        "channel_id": v.channel_id,
        "title": v.title or v.topic,
        "start": v.scheduled_at.isoformat(),
        "status": v.status,
        "review_status": v.review_status,
    } for v in query.all()]
    slots = db.query(ScheduledSlot).filter(ScheduledSlot.enabled.is_(True)).all()
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "items": items,
        "recurring_slots": [{
            "kind": "slot", "id": s.id, "channel_id": s.channel_id,
            "hour_utc": s.hour, "minute_utc": s.minute,
            "length_mode": s.length_mode, "categories": s.categories,
            "enabled": s.enabled,
        } for s in slots],
    }


@router.get("/errors")
def error_center(limit: int = 100, db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.status.in_(["failed", "dead"])).order_by(Job.id.desc()).limit(max(1, min(limit, 500))).all()
    videos = db.query(Video).filter(Video.status == "failed").order_by(Video.id.desc()).limit(max(1, min(limit, 500))).all()
    logs = db.query(ActivityLog).filter(ActivityLog.level.in_(["ERROR", "WARNING"])).order_by(ActivityLog.id.desc()).limit(max(1, min(limit, 500))).all()
    return {
        "jobs": [{"id": j.id, "type": j.type, "status": j.status, "attempts": j.attempts,
                  "max_attempts": j.max_attempts, "last_error": j.last_error,
                  "updated_at": j.updated_at.isoformat()} for j in jobs],
        "videos": [{"id": v.id, "title": v.title or v.topic, "status": v.status,
                    "error": v.error, "attempts": v.attempts,
                    "updated_at": v.updated_at.isoformat()} for v in videos],
        "logs": [{"id": l.id, "level": l.level, "source": l.source,
                  "message": l.message, "ts": l.ts.isoformat(), "context": l.context} for l in logs],
    }


@router.get("/backups")
def backups():
    return {"items": safety.list_backups(), "retention_days": settings.backup_retention_days}


@router.post("/backups", status_code=201)
def create_backup():
    try:
        return safety.create_backup()
    except Exception as exc:
        raise HTTPException(500, f"backup failed: {exc}") from exc


@router.post("/backups/{name}/restore")
def restore_backup(name: str, body: RestoreRequest):
    if not body.confirm:
        raise HTTPException(400, "restore requires confirm=true")
    try:
        return safety.restore_backup(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"restore failed: {exc}") from exc


@router.get("/notifications")
def notifications(channel_id: int | None = None, limit: int = 100):
    return {"items": safety.list_notifications(channel_id, limit),
            "enabled": settings.notifications_enabled}


@router.post("/notifications/test")
async def test_notification(channel_id: int | None = None, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.id == channel_id).first() if channel_id else db.query(Channel).first()
    if not channel:
        raise HTTPException(404, "channel not found")
    payload = {"type": "test", "channel_id": channel.id, "message": "Phoenix notification test"}
    delivered = await safety.deliver_webhook(payload)
    return safety.record_notification(channel.id, "test", "Phoenix notification test",
                                      "Notification test from Safety Center",
                                      delivered=delivered)


@router.get("/quota")
def quota():
    return safety.quota_status()
