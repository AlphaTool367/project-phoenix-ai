"""Crash recovery: runs once at startup.

- Videos stuck mid-pipeline (researching..uploading) are moved back to the
  last safe checkpoint status and re-queued as durable jobs.
- Jobs stuck in 'running' (process died mid-execution) are re-queued.
- Orphaned half-rendered work directories are left in place on purpose:
  the orchestrator treats existing files as checkpoints and resumes.
"""
from __future__ import annotations

from datetime import datetime

from ..core.logging import get_logger
from ..database import session_scope
from ..models import Job, Video

log = get_logger("recovery")

RESUMABLE = {
    "researching": "planned",
    "scripted": "planned",
    "voiced": "planned",
    "media_ready": "planned",
    "rendering": "rendered_or_retry",
    "uploading": "upload_retry",
}


def recover_interrupted_work() -> dict:
    videos_requeued = 0
    jobs_requeued = 0
    with session_scope() as db:
        stuck_jobs = db.query(Job).filter(Job.status == "running").all()
        for j in stuck_jobs:
            j.status = "queued"
            j.run_at = datetime.utcnow()
            jobs_requeued += 1

        stuck_videos = db.query(Video).filter(
            Video.status.in_(list(RESUMABLE.keys()))
        ).all()
        for v in stuck_videos:
            # JSON-path query on SQLite is unreliable — filter in Python.
            queued_jobs = db.query(Job).filter_by(
                type="produce_video", status="queued").all()
            already = any(
                (j.payload or {}).get("video_id") == v.id for j in queued_jobs
            )
            if already:
                continue
            if v.status == "rendering" and v.file_path:
                v.status = "rendered"  # render finished before crash
            elif v.status == "uploading":
                v.status = "rendered"
            else:
                v.status = "planned"
            db.add(Job(type="produce_video",
                       payload={"channel_id": v.channel_id, "video_id": v.id},
                       run_at=datetime.utcnow()))
            videos_requeued += 1

    if videos_requeued or jobs_requeued:
        log.warning("crash recovery: re-queued %d videos, %d jobs",
                    videos_requeued, jobs_requeued)
    else:
        log.info("crash recovery: nothing interrupted")
    return {"videos_requeued": videos_requeued, "jobs_requeued": jobs_requeued}
