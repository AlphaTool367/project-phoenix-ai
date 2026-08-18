"""Automation & scheduling.

APScheduler (AsyncIO) with a SQLite jobstore so schedules survive restarts:
  - 06:00 daily trend research per active channel
  - production slots at the channel's optimized publish hours
  - analytics sync every 6 hours
  - 02:30 nightly self-learning update
  - 30s durable job-queue worker (retries with backoff)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import settings
from ..core.logging import get_logger
from ..database import engine, session_scope
from ..models import Channel, Job, StrategyProfile

log = get_logger("scheduler")

_scheduler: AsyncIOScheduler | None = None


# ------------------------------------------------------------------ tasks
async def daily_research() -> None:
    from ..services import research

    with session_scope() as db:
        channels = db.query(Channel).filter_by(active=True).all()
    for ch in channels:
        try:
            await research.run_research(ch.id, ch.niche, ch.language)
        except Exception as exc:
            log.error("daily research failed for channel %s: %s", ch.id, exc)


async def daily_production() -> None:
    """Queue today's videos per channel into the durable job table."""
    with session_scope() as db:
        channels = db.query(Channel).filter_by(active=True).all()
        for ch in channels:
            strategy = db.query(StrategyProfile).filter_by(channel_id=ch.id).first()
            hours = (strategy.publish_hours if strategy else None) or [13, 17, 21]
            now = datetime.utcnow()
            for i in range(ch.videos_per_day):
                hour = hours[i % len(hours)]
                run_at = now.replace(hour=max(hour - 1, 0), minute=0, second=0)
                if run_at < now:
                    run_at = now + timedelta(minutes=5 + i * 10)
                # Count existing queued produce_video jobs for this channel
                # (JSON path query for SQLite is fragile, so filter in Python).
                queued = db.query(Job).filter_by(
                    type="produce_video", status="queued").all()
                existing_for_ch = sum(
                    1 for j in queued
                    if (j.payload or {}).get("channel_id") == ch.id
                )
                if existing_for_ch >= ch.videos_per_day:
                    break
                sched = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                db.add(Job(
                    type="produce_video",
                    payload={"channel_id": ch.id,
                             "scheduled_at": sched.isoformat() if sched > now else None},
                    run_at=run_at,
                ))
    log.info("daily production queued")


async def analytics_sync() -> None:
    from ..services import analytics

    with session_scope() as db:
        ids = [c.id for c in db.query(Channel).filter_by(active=True).all()]
    for cid in ids:
        try:
            await analytics.sync_channel_analytics(cid)
        except Exception as exc:
            log.error("analytics sync failed for channel %s: %s", cid, exc)


async def nightly_learning() -> None:
    from ..services import learning

    with session_scope() as db:
        ids = [c.id for c in db.query(Channel).all()]
    for cid in ids:
        try:
            await learning.update_strategy(cid)
        except Exception as exc:
            log.error("learning update failed for channel %s: %s", cid, exc)


async def queue_worker() -> None:
    """Execute due durable jobs with retry/backoff; one job per tick.

    Also fires any due ScheduledSlots (per-slot categories + length mode).
    """
    from ..pipeline.orchestrator import produce_video
    from ..models import ScheduledSlot

    # ---- 1. fire due scheduled slots ------------------------------------
    if settings.scheduler_auto_trigger:
        try:
            now = datetime.utcnow()
            with session_scope() as db:
                # A slot is "due" if its hour:minute matches now (within 30s)
                # AND it hasn't already fired today.
                today = now.date()
                due_slots = [
                    s for s in db.query(ScheduledSlot).filter_by(enabled=True).all()
                    if s.hour == now.hour
                    and abs(s.minute - now.minute) < 1
                    and (s.last_fired_at is None or s.last_fired_at.date() != today)
                ]
                for slot in due_slots:
                    slot.last_fired_at = now
                    log.info("firing scheduled slot #%d (channel=%d, mode=%s, cats=%s)",
                             slot.id, slot.channel_id, slot.length_mode, slot.categories)
                    # Fire in background — don't block the worker tick.
                    import asyncio as _a
                    _a.create_task(produce_video(
                        channel_id=slot.channel_id,
                        categories=slot.categories or None,
                        language_override=slot.language,
                        length_mode=slot.length_mode,
                        target_seconds=slot.target_seconds,
                        youtube_category_id=slot.youtube_category_id,
                        publish=True,
                    ))
        except Exception as exc:
            log.error("scheduled slot firing failed: %s", exc)

    # ---- 2. durable job queue worker ------------------------------------
    with session_scope() as db:
        job = db.query(Job).filter(
            Job.status == "queued", Job.run_at <= datetime.utcnow()
        ).order_by(Job.run_at).first()
        if job is None:
            return
        job.status = "running"
        job.attempts += 1
        job_id, jtype, payload = job.id, job.type, dict(job.payload)

    try:
        if jtype == "produce_video":
            sched = payload.get("scheduled_at")
            await produce_video(
                payload["channel_id"],
                scheduled_at=datetime.fromisoformat(sched) if sched else None,
            )
        elif jtype == "analytics_sync":
            await analytics_sync()
        status, err = "done", None
    except Exception as exc:
        status, err = "queued", str(exc)[:1500]
        log.warning("job %d (%s) failed: %s", job_id, jtype, exc)

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if status == "done":
            job.status = "done"
        elif job.attempts >= job.max_attempts:
            job.status = "dead"
            job.last_error = err
            log.error("job %d (%s) is DEAD after %d attempts", job_id, jtype, job.attempts)
        else:
            job.status = "queued"
            job.last_error = err
            job.run_at = datetime.utcnow() + timedelta(minutes=5 * job.attempts)


# ------------------------------------------------------------------ setup
def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=engine)},
        job_defaults={"coalesce": True, "max_instances": 1,
                      "misfire_grace_time": 3600},
    )

    # NOTE: jobs must be module-level callables so the SQLite jobstore can
    # pickle them by reference; AsyncIOScheduler runs coroutines natively.
    _scheduler.add_job(daily_research, "cron", hour=6, minute=0,
                       id="daily_research", replace_existing=True)
    _scheduler.add_job(daily_production, "cron", hour=6, minute=30,
                       id="daily_production", replace_existing=True)
    _scheduler.add_job(analytics_sync, "interval", hours=6,
                       id="analytics_sync", replace_existing=True)
    _scheduler.add_job(nightly_learning, "cron", hour=2, minute=30,
                       id="nightly_learning", replace_existing=True)
    _scheduler.add_job(queue_worker, "interval", seconds=30,
                       id="queue_worker", replace_existing=True)
    return _scheduler


def start() -> AsyncIOScheduler:
    sched = create_scheduler()
    if not sched.running:
        sched.start()
        log.info("scheduler started (%d jobs)", len(sched.get_jobs()))
    return sched


def snapshot() -> list[dict]:
    sched = create_scheduler()
    out = []
    for j in sched.get_jobs():
        nrt = getattr(j, "next_run_time", None)
        out.append({
            "id": j.id,
            "next_run": nrt.isoformat() if nrt else None,
            "trigger": str(getattr(j, "trigger", "")),
        })
    return out
