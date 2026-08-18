"""Revenue dashboard endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Channel
from ..services import revenue_tracker
from .deps import get_db

router = APIRouter(prefix="/api/revenue", tags=["revenue"])


@router.get("/dashboard/{channel_id}")
def dashboard(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    """Revenue dashboard — real if monetized, estimated otherwise."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return revenue_tracker.get_revenue_dashboard(channel_id, days=days)


@router.get("/top-videos/{channel_id}")
def top_videos(channel_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Top-earning videos (by estimated revenue)."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return revenue_tracker.get_top_earning_videos(channel_id, limit=limit)


@router.get("/niche-rpm")
def niche_rpm_table():
    """Return the niche RPM lookup table (for the dashboard's reference)."""
    return revenue_tracker.NICHE_RPM_USD


@router.post("/snapshot/{channel_id}")
def capture_snapshot(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    """Capture a revenue snapshot to the DB (for historical charting)."""
    from datetime import datetime
    from ..models import RevenueSnapshot
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    data = revenue_tracker.get_revenue_dashboard(channel_id, days=days)
    snap = RevenueSnapshot(
        channel_id=channel_id,
        period_days=days,
        total_revenue_usd=data.get("total_revenue_usd", 0),
        ad_revenue_usd=data.get("ad_revenue_usd", 0),
        views=data.get("views", 0),
        impressions=data.get("impressions", 0),
        monetized_playbacks=data.get("monetized_playbacks", 0),
        rpm_usd=data.get("rpm_usd", 0),
        cpm_usd=data.get("cpm_usd", 0),
        monetized=data.get("monetized", False),
        source=data.get("source", "estimated"),
    )
    db.add(snap)
    db.commit()
    return {"captured": True, "snapshot_id": snap.id, **data}


@router.get("/history/{channel_id}")
def revenue_history(channel_id: int, limit: int = 30, db: Session = Depends(get_db)):
    """Historical revenue snapshots (for charting)."""
    from ..models import RevenueSnapshot
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    rows = (db.query(RevenueSnapshot)
            .filter_by(channel_id=channel_id)
            .order_by(RevenueSnapshot.captured_at.desc())
            .limit(limit).all())
    return [{"captured_at": r.captured_at.isoformat(),
             "total_revenue_usd": r.total_revenue_usd,
             "views": r.views, "rpm_usd": r.rpm_usd, "cpm_usd": r.cpm_usd,
             "monetized": r.monetized, "source": r.source}
            for r in rows]
