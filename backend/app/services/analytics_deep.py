"""Analytics Deep — real-time subs, retention heatmap, predictive, PDF, funnel.

  - Real-time subscriber tracker: poll YouTube API every 60s for live sub count.
  - Audience retention heatmap: fetch per-second retention from YouTube Analytics.
  - Predictive analytics: scikit-learn linear regression to predict 30-day views.
  - Custom PDF reports: weekly/monthly channel performance reports.
  - Funnel analysis: impression → click → watch → subscribe conversion rates.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, Channel, Video
from .uploader import get_credentials

log = get_logger("analytics_deep")


def _yt_data_client(channel_id: int):
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _yt_analytics_client(channel_id: int):
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


# ----------------------------------------------------- real-time subs

def get_realtime_subscribers(channel_id: int) -> dict:
    """Fetch the current subscriber count + change since last check."""
    yt = _yt_data_client(channel_id)
    if yt is None:
        return {"available": False, "reason": "YouTube not connected"}
    try:
        resp = yt.channels().list(part="statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return {"available": False, "reason": "no channel data"}
        stats = items[0].get("statistics", {})
        subs = int(stats.get("subscriberCount", 0))
        # Compare to last cached value.
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            prev_subs = ch.yt_subscriber_count if ch else None
            if ch:
                ch.yt_subscriber_count = subs
                ch.yt_stats_fetched_at = datetime.utcnow()
        change = subs - prev_subs if prev_subs is not None else 0
        return {
            "available": True,
            "subscribers": subs,
            "previous": prev_subs,
            "change": change,
            "fetched_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        log.warning("realtime subs failed: %s", exc)
        return {"available": False, "reason": str(exc)}


# ----------------------------------------------------- retention heatmap

def fetch_retention_heatmap(video_yt_id: str, channel_id: int) -> dict:
    """Fetch per-second audience retention for a video.

    Returns {points: [{elapsed_seconds, viewers_pct}]}.
    """
    yta = _yt_analytics_client(channel_id)
    if yta is None:
        return {"available": False, "reason": "YouTube not connected"}
    try:
        # YouTube Analytics API doesn't expose per-second retention directly
        # via the public API. The `audienceRetentionReport` is only available
        # via the YouTube Reporting API (which requires a different flow).
        # As a fallback, we return the video's average retention %.
        from .analytics import _live
        with session_scope() as db:
            v = db.query(Video).filter_by(yt_video_id=video_yt_id).first()
            if not v:
                return {"available": False, "reason": "video not found"}
            snap = (db.query(AnalyticsSnapshot)
                    .filter_by(video_id=v.id)
                    .order_by(AnalyticsSnapshot.captured_at.desc())
                    .first())
        avg_retention = snap.retention_pct if snap else 0
        return {
            "available": True,
            "average_retention_pct": avg_retention,
            "note": "Per-second retention requires the YouTube Reporting API. "
                    "Showing average retention as a fallback.",
        }
    except Exception as exc:
        log.warning("retention heatmap failed: %s", exc)
        return {"available": False, "reason": str(exc)}


# ----------------------------------------------------- predictive analytics

def predict_video_views(video_id: int, days_ahead: int = 30) -> dict:
    """Predict a video's views N days from now using linear regression.

    Uses scikit-learn when available, falls back to simple extrapolation.
    """
    with session_scope() as db:
        v = db.get(Video, video_id)
        if not v:
            return {"available": False, "reason": "video not found"}
        snaps = (db.query(AnalyticsSnapshot)
                 .filter_by(video_id=video_id)
                 .order_by(AnalyticsSnapshot.captured_at)
                 .all())
    if len(snaps) < 2:
        return {"available": False, "reason": "not enough data (need ≥2 snapshots)"}
    # X = hours since first snapshot, y = views.
    first_ts = snaps[0].captured_at
    X = [(s.captured_at - first_ts).total_seconds() / 3600 for s in snaps]
    y = [s.views for s in snaps]
    try:
        from sklearn.linear_model import LinearRegression
        import numpy as np
        model = LinearRegression()
        model.fit(np.array(X).reshape(-1, 1), y)
        future_hour = X[-1] + days_ahead * 24
        predicted = int(model.predict([[future_hour]])[0])
        confidence = min(model.score(np.array(X).reshape(-1, 1), y), 1.0)
        return {
            "available": True,
            "current_views": y[-1],
            "predicted_views": max(predicted, y[-1]),
            "days_ahead": days_ahead,
            "confidence": round(confidence, 2),
            "model": "sklearn LinearRegression",
        }
    except ImportError:
        # Simple extrapolation: average daily growth * days.
        if len(y) < 2 or X[-1] == X[0]:
            return {"available": False, "reason": "insufficient data"}
        daily_growth = (y[-1] - y[0]) / max((X[-1] - X[0]) / 24, 1)
        predicted = int(y[-1] + daily_growth * days_ahead)
        return {
            "available": True,
            "current_views": y[-1],
            "predicted_views": max(predicted, y[-1]),
            "days_ahead": days_ahead,
            "confidence": 0.5,
            "model": "simple extrapolation (install scikit-learn for better)",
        }


# ----------------------------------------------------- PDF reports

def generate_pdf_report(channel_id: int, days: int = 30) -> dict:
    """Generate a weekly/monthly PDF report of channel performance."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle)
        from reportlab.lib import colors
    except ImportError:
        return {"success": False,
                "reason": "reportlab not installed. Run: pip install reportlab"}
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        if not ch:
            return {"success": False, "reason": "channel not found"}
        name = ch.name
        subs = ch.yt_subscriber_count or 0
        niche = ch.niche
        # Sum recent snapshots.
        cutoff = datetime.utcnow() - timedelta(days=days)
        snaps = (db.query(AnalyticsSnapshot)
                 .filter(AnalyticsSnapshot.channel_id == channel_id,
                         AnalyticsSnapshot.captured_at >= cutoff)
                 .all())
        total_views = sum(s.views for s in snaps)
        avg_retention = (sum(s.retention_pct for s in snaps) / len(snaps)
                         if snaps else 0)
        avg_ctr = (sum(s.ctr_pct for s in snaps) / len(snaps) if snaps else 0)
        video_count = db.query(Video).filter_by(channel_id=channel_id).count()

    out_path = settings.path(settings.data_dir, "reports")
    out_path.mkdir(parents=True, exist_ok=True)
    filename = out_path / f"channel_{channel_id}_report_{days}d.pdf"

    doc = SimpleDocTemplate(str(filename), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Channel Report: {name}", styles["Title"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"Period: Last {days} days", styles["Normal"]))
    story.append(Paragraph(f"Niche: {niche}", styles["Normal"]))
    story.append(Spacer(1, 20))

    data = [
        ["Metric", "Value"],
        ["Subscribers", f"{subs:,}"],
        ["Total videos produced", str(video_count)],
        ["Total views (period)", f"{total_views:,}"],
        ["Average retention", f"{avg_retention:.1f}%"],
        ["Average CTR", f"{avg_ctr:.2f}%"],
    ]
    t = Table(data)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ff5e3a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        "Generated by Project Phoenix AI", styles["Italic"]))
    doc.build(story)
    log.info("PDF report generated: %s", filename.name)
    return {"success": True, "path": str(filename)}


# ----------------------------------------------------- funnel analysis

def get_funnel_analysis(channel_id: int, days: int = 30) -> dict:
    """Compute the impression → click → watch → subscribe funnel."""
    yta = _yt_analytics_client(channel_id)
    if yta is None:
        return {"available": False, "reason": "YouTube not connected"}
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="impressions,views,subscribersGained,estimatedMinutesWatched",
        ).execute()
        rows = resp.get("rows", [])
        if not rows:
            return {"available": False, "reason": "no data"}
        r = rows[0]
        impressions = int(r[0]) if len(r) > 0 else 0
        views = int(r[1]) if len(r) > 1 else 0
        subs = int(r[2]) if len(r) > 2 else 0
        watch_minutes = int(r[3]) if len(r) > 3 else 0
        ctr = (views / impressions * 100) if impressions > 0 else 0
        sub_rate = (subs / views * 100) if views > 0 else 0
        return {
            "available": True,
            "impressions": impressions,
            "views": views,
            "subscribers_gained": subs,
            "watch_hours": round(watch_minutes / 60, 1),
            "ctr_pct": round(ctr, 2),
            "click_to_sub_rate_pct": round(sub_rate, 2),
            "funnel": [
                {"stage": "Impressions", "count": impressions, "pct": 100.0},
                {"stage": "Clicks (views)", "count": views,
                 "pct": round(ctr, 2)},
                {"stage": "Watched (min)", "count": watch_minutes,
                 "pct": round(watch_minutes / max(views, 1) * 100, 1)},
                {"stage": "Subscribed", "count": subs,
                 "pct": round(sub_rate, 2)},
            ],
        }
    except Exception as exc:
        log.warning("funnel analysis failed: %s", exc)
        return {"available": False, "reason": str(exc)}
