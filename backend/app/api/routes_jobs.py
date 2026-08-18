"""Job queue management + scheduler control."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Job
from ..pipeline import scheduler as sched
from ..schemas import JobOut
from .deps import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Job).order_by(Job.id.desc())
    if status:
        q = q.filter(Job.status == status)
    return q.limit(min(limit, 500)).all()


@router.post("/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job.status = "queued"
    job.attempts = 0
    job.run_at = datetime.utcnow()
    db.commit()
    return {"requeued": True}


@router.get("/scheduler")
def scheduler_jobs():
    return sched.snapshot()


@router.post("/scheduler/{action}")
def scheduler_control(action: str):
    s = sched.create_scheduler()
    if action == "start":
        sched.start()
    elif action == "pause":
        if s.running:
            s.pause()
    elif action == "resume":
        if not s.running:
            try:
                s.start()
            except Exception:
                pass
        else:
            s.resume()
    else:
        raise HTTPException(400, "action must be start|pause|resume")
    # 'state' reflects running status; paused jobs are still 'running' from
    # the scheduler's lifecycle POV but won't fire until resumed.
    return {"state": "running" if s.running else "stopped", "action": action}
