"""Scheduled slot management + manual trigger.

A ScheduledSlot is a user-defined production slot that fires at a set time
each day. The scheduler picks due slots and produces one video per slot.

Endpoints:
  GET    /api/scheduler/slots                list all slots
  POST   /api/scheduler/slots                create a new slot
  PATCH  /api/scheduler/slots/{id}           update a slot
  DELETE /api/scheduler/slots/{id}           delete a slot
  POST   /api/scheduler/slots/{id}/fire      manually trigger a slot now
  POST   /api/scheduler/slots/{id}/toggle    enable / disable a slot
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..core.logging import get_logger
from ..models import ScheduledSlot
from ..schemas import ScheduledSlotCreate, ScheduledSlotOut, ScheduledSlotUpdate
from .deps import get_db

log = get_logger("scheduler_routes")
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/slots", response_model=list[ScheduledSlotOut])
def list_slots(channel_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(ScheduledSlot).order_by(ScheduledSlot.hour, ScheduledSlot.minute)
    if channel_id:
        q = q.filter(ScheduledSlot.channel_id == channel_id)
    return q.all()


@router.post("/slots", response_model=ScheduledSlotOut, status_code=201)
def create_slot(body: ScheduledSlotCreate, db: Session = Depends(get_db)):
    slot = ScheduledSlot(**body.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    log.info("created slot #%d: channel=%d @ %02d:%02d (mode=%s, cats=%s)",
             slot.id, slot.channel_id, slot.hour, slot.minute,
             slot.length_mode, slot.categories)
    return slot


@router.patch("/slots/{slot_id}", response_model=ScheduledSlotOut)
def update_slot(slot_id: int, body: ScheduledSlotUpdate,
                db: Session = Depends(get_db)):
    slot = db.get(ScheduledSlot, slot_id)
    if not slot:
        raise HTTPException(404, "slot not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(slot, k, v)
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/slots/{slot_id}")
def delete_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(ScheduledSlot, slot_id)
    if not slot:
        raise HTTPException(404, "slot not found")
    db.delete(slot)
    db.commit()
    return {"deleted": True}


@router.post("/slots/{slot_id}/toggle", response_model=ScheduledSlotOut)
def toggle_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(ScheduledSlot, slot_id)
    if not slot:
        raise HTTPException(404, "slot not found")
    slot.enabled = not slot.enabled
    db.commit()
    db.refresh(slot)
    return slot


@router.post("/slots/{slot_id}/fire", status_code=202)
async def fire_slot(slot_id: int, background: BackgroundTasks,
                    db: Session = Depends(get_db)):
    """Manually trigger a scheduled slot now (ignores its time + enabled flag)."""
    import asyncio
    from ..pipeline.orchestrator import produce_video

    slot = db.get(ScheduledSlot, slot_id)
    if not slot:
        raise HTTPException(404, "slot not found")

    async def _run():
        try:
            await produce_video(
                channel_id=slot.channel_id,
                categories=slot.categories or None,
                language_override=slot.language,
                length_mode=slot.length_mode,
                target_seconds=slot.target_seconds,
                youtube_category_id=slot.youtube_category_id,
                publish=True,
            )
        except Exception as exc:
            log.exception("manual fire of slot %d failed: %s", slot_id, exc)

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    slot.last_fired_at = datetime.utcnow()
    db.commit()
    return {"started": True, "slot_id": slot_id,
            "channel_id": slot.channel_id,
            "length_mode": slot.length_mode,
            "categories": slot.categories}


@router.get("/settings")
def scheduler_settings():
    """Expose the scheduler-related settings to the dashboard."""
    return {
        "auto_trigger": settings.scheduler_auto_trigger,
        "copyright_check_enabled": settings.copyright_check_enabled,
        "copyright_wait_seconds": settings.copyright_wait_seconds,
        "auto_publish_after_check": settings.auto_publish_after_check,
        "post_check_privacy": settings.post_check_privacy,
    }
