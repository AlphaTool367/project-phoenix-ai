"""Revenue tracker — RPM/CPM calculator + revenue dashboard.

Uses the YouTube Analytics API v2 to fetch revenue metrics for the
channel and stores them in a RevenueSnapshot table. The dashboard
shows daily/weekly/monthly revenue + RPM (revenue per 1K views) +
CPM (cost per 1K impressions).

YouTube Analytics API returns revenue data ONLY for channels that are
already monetized (in the YouTube Partner Program). For non-monetized
channels, we estimate potential revenue using a niche-based RPM table.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..core.logging import get_logger
from ..database import session_scope
from ..models import Channel, Video
from .uploader import get_credentials

log = get_logger("revenue")

# Average RPM (revenue per 1K views) in USD by niche — these are rough
# industry averages for English-language content. Used for estimation
# when the channel isn't monetized yet.
NICHE_RPM_USD = {
    "finance": 18.0, "business": 15.0, "technology": 12.0,
    "education": 10.0, "science": 8.0, "health": 8.0,
    "history": 6.0, "space": 6.0, "entertainment": 4.0,
    "gaming": 4.0, "music": 3.0, "lifestyle": 5.0,
    "news": 6.0, "travel": 7.0, "food": 6.0, "fitness": 7.0,
    "sports": 5.0, "automotive": 9.0, "diy": 5.0, "art": 4.0,
    "psychology": 8.0, "philosophy": 6.0, "politics": 5.0, "fashion": 6.0,
}
DEFAULT_RPM = 5.0


def _yt_analytics_client(channel_id: int):
    """Build a YouTube Analytics API client for the channel."""
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def fetch_revenue_metrics(channel_id: int, days: int = 30) -> dict | None:
    """Fetch real revenue metrics for the last `days` days.

    Returns None when the channel isn't connected or not monetized.
    """
    yta = _yt_analytics_client(channel_id)
    if yta is None:
        return None
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="estimatedRevenue,estimatedAdRevenue,estimatedWatchTime,views,impressions,monetizedPlaybacks",
            dimensions="day",
            sort="day",
        ).execute()
        rows = resp.get("rows", [])
        if not rows:
            return None
        # Sum up.
        total_revenue = sum(float(r[1]) for r in rows if r[1] is not None)
        total_ad_revenue = sum(float(r[2]) for r in rows if r[2] is not None)
        total_watch_hours = sum(float(r[3]) for r in rows if r[3] is not None) / 3600.0
        total_views = sum(int(r[4]) for r in rows if r[4] is not None)
        total_impressions = sum(int(r[5]) for r in rows if r[5] is not None)
        monetized = sum(int(r[6]) for r in rows if r[6] is not None)
        rpm = (total_revenue / max(total_views, 1)) * 1000 if total_views else 0
        cpm = (total_ad_revenue / max(total_impressions, 1)) * 1000 if total_impressions else 0
        return {
            "period_days": days,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "total_revenue_usd": round(total_revenue, 2),
            "ad_revenue_usd": round(total_ad_revenue, 2),
            "watch_hours": round(total_watch_hours, 1),
            "views": total_views,
            "impressions": total_impressions,
            "monetized_playbacks": monetized,
            "rpm_usd": round(rpm, 2),
            "cpm_usd": round(cpm, 2),
            "monetized": True,
            "source": "youtube_analytics",
            "fetched_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        log.warning("revenue fetch failed: %s", exc)
        return None


def estimate_potential_revenue(channel_id: int, days: int = 30) -> dict:
    """Estimate potential revenue for a non-monetized channel.

    Uses the niche-based RPM table + the channel's actual view count
    from AnalyticsSnapshot (sync query — no async call needed).
    """
    from ..models import AnalyticsSnapshot
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        niche = ch.niche if ch else "technology"
        # Sum the latest snapshot per video.
        snaps = (db.query(AnalyticsSnapshot)
                 .filter_by(channel_id=channel_id)
                 .order_by(AnalyticsSnapshot.captured_at.desc())
                 .all())
        latest: dict[int, AnalyticsSnapshot] = {}
        for s in snaps:
            if s.video_id is not None:
                latest.setdefault(s.video_id, s)
        rows = list(latest.values())
        views = sum(r.views for r in rows)
        videos = len(rows)
    rpm = NICHE_RPM_USD.get(niche, DEFAULT_RPM)
    estimated = (views / 1000.0) * rpm
    return {
        "period_days": days,
        "total_revenue_usd": round(estimated, 2),
        "ad_revenue_usd": round(estimated, 2),
        "views": views,
        "videos": videos,
        "rpm_usd": rpm,
        "cpm_usd": round(rpm * 0.7, 2),  # CPM is typically ~70% of RPM
        "monetized": False,
        "source": "estimated",
        "niche": niche,
        "note": (f"Estimated using average RPM for niche '{niche}' (${rpm}/1K views). "
                 f"Actual revenue will vary based on audience geography, watch time, "
                 f"and advertiser demand. Connect YouTube + join YPP for real data."),
        "fetched_at": datetime.utcnow().isoformat(),
    }


def get_revenue_dashboard(channel_id: int, days: int = 30) -> dict:
    """Get the revenue dashboard data — real if monetized, estimated otherwise."""
    real = fetch_revenue_metrics(channel_id, days=days)
    if real is not None:
        return real
    return estimate_potential_revenue(channel_id, days=days)


def get_per_video_revenue_estimate(video: Video) -> dict:
    """Estimate revenue for a single video based on its niche + views.

    Returns {estimated_revenue_usd, rpm_usd, views, niche}
    """
    from .analytics import _simulated
    # Pull the latest snapshot for this video.
    with session_scope() as db:
        from ..models import AnalyticsSnapshot
        snap = (db.query(AnalyticsSnapshot)
                .filter_by(video_id=video.id)
                .order_by(AnalyticsSnapshot.captured_at.desc())
                .first())
        views = snap.views if snap else 0
    rpm = NICHE_RPM_USD.get(video.niche, DEFAULT_RPM)
    estimated = (views / 1000.0) * rpm
    return {
        "video_id": video.id,
        "title": video.title or video.topic,
        "niche": video.niche,
        "views": views,
        "rpm_usd": rpm,
        "estimated_revenue_usd": round(estimated, 2),
        "monetized": False,
        "source": "estimated",
    }


def get_top_earning_videos(channel_id: int, limit: int = 10) -> list[dict]:
    """List the channel's top-earning videos (by estimated revenue)."""
    with session_scope() as db:
        from ..models import AnalyticsSnapshot
        rows = (db.query(Video, AnalyticsSnapshot)
                .join(AnalyticsSnapshot, AnalyticsSnapshot.video_id == Video.id)
                .filter(Video.channel_id == channel_id)
                .order_by(AnalyticsSnapshot.captured_at.desc())
                .all())
        seen: dict[int, dict] = {}
        for v, s in rows:
            if v.id in seen:
                continue
            seen[v.id] = get_per_video_revenue_estimate(v)
        ranked = sorted(seen.values(), key=lambda x: x["estimated_revenue_usd"],
                        reverse=True)
        return ranked[:limit]
