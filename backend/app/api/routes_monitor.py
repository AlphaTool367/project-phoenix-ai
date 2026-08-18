"""YouTube realtime monitor endpoints.

Searches YouTube for top-performing videos in a niche, stores them in the
TrendingVideo table, and extracts LearnedInsight rows from them via the LLM.
Also exposes cached trending videos + insights for the dashboard.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Channel, TrendReport
from ..schemas import LearnedInsightOut, MonitorSearchRequest, TrendingVideoOut
from ..services import monitor, research
from .deps import get_db

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.post("/search")
async def search(body: MonitorSearchRequest, db: Session = Depends(get_db)):
    """Search YouTube for top videos in a niche + extract insights."""
    if not db.get(Channel, body.channel_id):
        raise HTTPException(404, "channel not found")
    try:
        result = await monitor.search_and_learn(
            channel_id=body.channel_id,
            query=body.query,
            niches=body.niches,
            region_code=body.region_code,
            min_views=body.min_views,
            max_results=body.max_results,
            learn=body.learn,
        )
        return result
    except Exception as exc:
        raise HTTPException(500, f"monitor search failed: {exc}") from exc


@router.get("/trending/{channel_id}", response_model=list[TrendingVideoOut])
def list_trending(channel_id: int, niche: str | None = None,
                  limit: int = 50, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return monitor.list_trending_videos(channel_id, niche=niche, limit=limit)


@router.get("/insights/{channel_id}", response_model=list[LearnedInsightOut])
def list_insights(channel_id: int, niche: str | None = None,
                  insight_type: str | None = None, limit: int = 100,
                  db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return monitor.list_insights(channel_id, niche=niche,
                                  insight_type=insight_type, limit=limit)


@router.get("/inspiration/{channel_id}/{niche}")
def get_inspiration(channel_id: int, niche: str, db: Session = Depends(get_db)):
    """Return a short inspiration string for a niche — used by the scriptwriter."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    text = monitor.get_inspiration_for_niche(channel_id, niche)
    return {"niche": niche, "inspiration": text}


@router.post("/extract/{channel_id}")
async def extract_insights_now(channel_id: int, max_videos: int = 10,
                                db: Session = Depends(get_db)):
    """Run the insight extraction pass over un-analyzed trending videos."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    count = await monitor.extract_insights(channel_id, max_videos=max_videos)
    return {"extracted": count}


@router.get("/upload-times/{channel_id}")
def suggest_upload_times(channel_id: int, db: Session = Depends(get_db)):
    """Suggest the best upload hours based on the channel's learning profile."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return {"hours": monitor.suggest_upload_times(channel_id)}


@router.post("/research/{channel_id}")
async def run_topic_research(channel_id: int, niche: str | None = None,
                             limit: int = 10, db: Session = Depends(get_db)):
    """Run automatic real-source topic research and persist the report."""
    channel = db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "channel not found")
    report = await research.run_research(
        channel_id, niche or channel.niche, channel.language, max(1, min(limit, 30))
    )
    return {
        "id": report.id,
        "date": report.date,
        "source": report.source,
        "winning_niche": report.winning_niche,
        "topics": report.topics,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/research/latest/{channel_id}")
def latest_topic_research(channel_id: int, db: Session = Depends(get_db)):
    """Return the latest automatic topic research report, if one exists."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    report = (db.query(TrendReport).filter_by(channel_id=channel_id)
              .order_by(TrendReport.created_at.desc()).first())
    if not report:
        return {"available": False, "topics": [], "source": "none"}
    return {
        "available": True,
        "id": report.id,
        "date": report.date,
        "source": report.source,
        "winning_niche": report.winning_niche,
        "topics": report.topics or [],
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/stats/{channel_id}")
def monitor_stats(channel_id: int, db: Session = Depends(get_db)):
    """Quick stats for the monitor dashboard card."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return {
        "trending_count": len(monitor.list_trending_videos(channel_id, limit=500)),
        "insights_count": len(monitor.list_insights(channel_id, limit=500)),
        "min_views": __import__("app.config", fromlist=["settings"]).settings.monitor_min_views,
        "daily_quota": __import__("app.config", fromlist=["settings"]).settings.monitor_daily_quota,
    }
