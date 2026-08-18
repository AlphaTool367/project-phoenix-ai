"""Analytics & performance tracking.

Live mode: YouTube Analytics API + Data API per published video.
Mock mode: seeded, time-aware metric simulation — lets the learning loop
and the dashboard charts work before any real upload exists.

Robust against 404s from the YouTube Analytics API when the channel has no
analytics data yet (brand-new channel, no published videos, etc.) — every
failure path returns None so the caller falls back to simulated data instead
of bubbling a 404 up to the dashboard.
"""
from __future__ import annotations

import math
import random
from datetime import datetime

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, Channel, Video
from .uploader import get_credentials

log = get_logger("analytics")


def _simulated(video: Video, now: datetime) -> dict:
    """Plausible growth curve: fast first 48h, long tail. Deterministic per video."""
    published = video.published_at or video.created_at
    age_h = max((now - published).total_seconds() / 3600, 1)
    rng = random.Random(video.id * 7919)
    base = rng.uniform(300, 4000)
    views = int(base * math.log1p(age_h) * rng.uniform(0.8, 1.25))
    retention = min(max(rng.gauss(42, 9), 12), 88)
    ctr = min(max(rng.gauss(5.5, 1.8), 1.0), 14)
    return {
        "views": views,
        "watch_minutes": round(views * video.duration_seconds / 60 * retention / 100, 1),
        "avg_view_duration": round(video.duration_seconds * retention / 100, 1),
        "retention_pct": round(retention, 1),
        "ctr_pct": round(ctr, 2),
        "likes": int(views * rng.uniform(0.02, 0.06)),
        "comments": int(views * rng.uniform(0.002, 0.008)),
        "shares": int(views * rng.uniform(0.003, 0.012)),
        "subs_gained": int(views * rng.uniform(0.004, 0.015)),
        "source": "simulated",
    }


def _live(video: Video) -> dict | None:
    """Pull live analytics for one video from YouTube.

    Returns None on any unavailable live-data condition. The caller decides
    whether synthetic metrics are explicitly allowed; this function never
    silently turns a live-tracking failure into fake numbers.
    """
    creds = get_credentials(video.channel_id)
    if creds is None or not video.yt_video_id or video.yt_video_id.startswith("DRYRUN"):
        return None
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

        start = (video.published_at or video.created_at).strftime("%Y-%m-%d")
        end = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            rep = yta.reports().query(
                ids="channel==MINE", startDate=start, endDate=end,
                metrics=("views,estimatedMinutesWatched,averageViewDuration,"
                         "subscribersGained,likes,comments,shares"),
                filters=f"video=={video.yt_video_id}",
            ).execute()
            row = (rep.get("rows") or [[0] * 7])[0]
        except HttpError as exc:
            # 404 / 400 are normal for a brand-new video with no data yet.
            if exc.resp.status in (400, 404):
                row = [0] * 7
            else:
                raise

        # Pull like / comment / view counts from the Data API (always works).
        likes = comments = views_from_stats = 0
        try:
            stats = yt.videos().list(part="statistics", id=video.yt_video_id).execute()
            s = (stats.get("items") or [{}])[0].get("statistics", {}) or {}
            likes = int(s.get("likeCount", 0) or 0)
            comments = int(s.get("commentCount", 0) or 0)
            views_from_stats = int(s.get("viewCount", 0) or 0)
        except HttpError as exc:
            if exc.resp.status not in (400, 404):
                log.warning("video stats fetch failed for %s: %s", video.yt_video_id, exc)

        views = int(row[0]) if row and len(row) > 0 else views_from_stats
        return {
            "views": max(views, views_from_stats),
            "watch_minutes": float(row[1]) if len(row) > 1 else 0.0,
            "avg_view_duration": float(row[2]) if len(row) > 2 else 0.0,
            "retention_pct": (
                round(float(row[2]) / max(video.duration_seconds, 1) * 100, 1)
                if len(row) > 2 and video.duration_seconds else 0.0
            ),
            "ctr_pct": 0.0,
            "likes": likes,
            "comments": comments,
            "shares": int(row[6]) if len(row) > 6 else 0,
            "subs_gained": int(row[3]) if len(row) > 3 else 0,
            "source": "youtube",
        }
    except Exception as exc:
        log.warning("live analytics failed for video %s: %s", video.id, exc)
        return None


async def sync_channel_analytics(channel_id: int) -> int:
    """Snapshot analytics for every published video of a channel."""
    now = datetime.utcnow()
    count = 0
    with session_scope() as db:
        videos = db.query(Video).filter(
            Video.channel_id == channel_id,
            Video.status.in_(["published", "scheduled"]),
        ).all()
        for v in videos:
            data = _live(v)
            if data is None:
                if not settings.allow_simulated_metrics:
                    log.warning(
                        "live analytics unavailable for video %s; skipping snapshot "
                        "because ALLOW_SIMULATED_METRICS is false",
                        v.id,
                    )
                    continue
                data = _simulated(v, now)
            db.add(AnalyticsSnapshot(video_id=v.id, channel_id=channel_id, **data))
            count += 1
    log.info("analytics synced: %d videos (channel %d)", count, channel_id)
    return count


async def channel_summary(channel_id: int) -> dict:
    """Aggregated latest-per-video stats for the dashboard."""
    with session_scope() as db:
        snaps = (
            db.query(AnalyticsSnapshot)
            .filter(AnalyticsSnapshot.channel_id == channel_id)
            .order_by(AnalyticsSnapshot.captured_at.desc())
            .all()
        )
        # Include the live YouTube channel stats (subscribers / total views)
        ch = db.get(Channel, channel_id)
        yt_subs = ch.yt_subscriber_count if ch else None
        yt_total_views = ch.yt_view_count if ch else None
        yt_video_count = ch.yt_video_count if ch else None
        yt_fetched = ch.yt_stats_fetched_at.isoformat() if (ch and ch.yt_stats_fetched_at) else None
        channel_name = ch.name if ch else None
        yt_channel_id = ch.yt_channel_id if ch else None
        yt_thumbnail = ch.yt_thumbnail if ch else None
    latest: dict[int, AnalyticsSnapshot] = {}
    for s in snaps:
        latest.setdefault(s.video_id, s)
    rows = list(latest.values())
    sources = {str(r.source or "unknown") for r in rows}
    metrics_source = (
        "none" if not sources else
        "youtube" if sources == {"youtube"} else
        "simulated" if sources == {"simulated"} else
        "mixed"
    )
    base = {
        "videos": len(rows),
        "metrics_source": metrics_source,
        "metrics_are_live": metrics_source == "youtube",
        "simulation_allowed": settings.allow_simulated_metrics,
        "views": sum(r.views for r in rows),
        "watch_minutes": round(sum(r.watch_minutes for r in rows), 1),
        "subs_gained": sum(r.subs_gained for r in rows),
        "avg_retention": round(sum(r.retention_pct for r in rows) / len(rows), 1) if rows else 0,
        "avg_ctr": round(sum(r.ctr_pct for r in rows) / len(rows), 2) if rows else 0,
        "likes": sum(r.likes for r in rows),
        "comments": sum(r.comments for r in rows),
        "shares": sum(r.shares for r in rows),
        # Live YouTube channel stats (may be None when not connected yet).
        "channel_name": channel_name,
        "yt_channel_id": yt_channel_id,
        "yt_thumbnail": yt_thumbnail,
        "yt_subscriber_count": yt_subs,
        "yt_total_views": yt_total_views,
        "yt_video_count": yt_video_count,
        "yt_stats_fetched_at": yt_fetched,
        "connected": yt_channel_id is not None,
    }
    return base


async def realtime_channel_overview(channel_id: int) -> dict:
    """Live YouTube channel snapshot + local rollup, for the dashboard header.

    Refreshes the cached channel stats first so the numbers stay fresh. Always
    returns a dict (never raises) — when YouTube isn't connected we fall back
    to whatever is cached locally and flag `connected: false`.
    """
    from .uploader import fetch_live_channel_stats, is_oauth_connected

    connected = is_oauth_connected(channel_id)
    live = None
    if connected:
        live = fetch_live_channel_stats(channel_id)  # updates DB too
    summary = await channel_summary(channel_id)
    summary["connected"] = connected
    if live:
        summary["channel_name"] = live.get("title") or summary.get("channel_name")
        summary["yt_subscriber_count"] = live.get("subscriber_count")
        summary["yt_total_views"] = live.get("view_count")
        summary["yt_video_count"] = live.get("video_count")
        summary["yt_thumbnail"] = live.get("thumbnail") or summary.get("yt_thumbnail")
        summary["yt_country"] = live.get("country")
        summary["live_fetched_at"] = live.get("fetched_at")
    return summary
