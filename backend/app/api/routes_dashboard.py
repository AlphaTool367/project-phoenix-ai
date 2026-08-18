"""Dashboard summary: live status, queue, health, storage, activity."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import ActivityLog, Channel, Job, Video
from ..pipeline.orchestrator import RENDER_PROGRESS
from ..pipeline.scheduler import snapshot as scheduler_snapshot
from ..services import health
from .deps import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    status_counts = {
        status: count
        for status, count in db.query(
            Video.status, func.count(Video.id)
        ).group_by(Video.status).all()
    }
    queued_jobs = db.query(Job).filter(Job.status == "queued").count()
    running_jobs = db.query(Job).filter(Job.status == "running").count()
    dead_jobs = db.query(Job).filter(Job.status == "dead").count()
    recent_logs = (
        db.query(ActivityLog).order_by(ActivityLog.id.desc()).limit(12).all()
    )
    return {
        "channels": db.query(Channel).count(),
        "videos_total": sum(status_counts.values()),
        "videos_by_status": status_counts,
        "rendering_now": RENDER_PROGRESS,
        "queue": {"queued": queued_jobs, "running": running_jobs, "dead": dead_jobs},
        "system": health.system_stats(),
        "storage": health.storage_breakdown(),
        "capabilities": health.api_health(),
        "scheduler": scheduler_snapshot(),
        "recent_activity": [
            {"ts": l.ts.isoformat(), "level": l.level, "source": l.source,
             "message": l.message}
            for l in recent_logs
        ],
    }


@router.get("/health")
def health_detail():
    return {**health.api_health(), "system": health.system_stats(),
            "storage": health.storage_breakdown()}


@router.get("/logs")
def logs(limit: int = 100, level: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ActivityLog).order_by(ActivityLog.id.desc())
    if level:
        q = q.filter(ActivityLog.level == level.upper())
    rows = q.limit(min(limit, 500)).all()
    return [
        {"id": l.id, "ts": l.ts.isoformat(), "level": l.level,
         "source": l.source, "message": l.message}
        for l in rows
    ]
