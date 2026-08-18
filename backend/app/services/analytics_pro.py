"""Analytics Pro — demographics, traffic sources, real-time subs, anomaly, sentiment.

Extends the existing analytics service with deeper YouTube Analytics API
queries that break down views by demographics, geography, and traffic
source. Also provides real-time subscriber tracking and anomaly detection.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, Channel, Video
from .uploader import get_credentials

log = get_logger("analytics_pro")


def _yta_client(channel_id: int):
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def fetch_demographics(channel_id: int, days: int = 30) -> dict:
    """Fetch age + gender breakdown for the channel."""
    yta = _yta_client(channel_id)
    if yta is None:
        return {"available": False, "reason": "YouTube not connected"}
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views,estimatedMinutesWatched,subscribersGained",
            dimensions="ageGroup,gender",
            sort="-views",
        ).execute()
        rows = resp.get("rows", [])
        out = []
        for r in rows:
            out.append({
                "age_group": r[0] or "unknown",
                "gender": r[1] or "unknown",
                "views": int(r[2]) if len(r) > 2 else 0,
                "watch_minutes": int(r[3]) if len(r) > 3 else 0,
                "subs_gained": int(r[4]) if len(r) > 4 else 0,
            })
        return {"available": True, "breakdown": out, "days": days}
    except Exception as exc:
        log.warning("demographics fetch failed: %s", exc)
        return {"available": False, "reason": str(exc)}


def fetch_traffic_sources(channel_id: int, days: int = 30) -> dict:
    """Fetch traffic source breakdown (search, suggested, browse, external, etc.)."""
    yta = _yta_client(channel_id)
    if yta is None:
        return {"available": False, "reason": "YouTube not connected"}
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            sort="-views",
        ).execute()
        rows = resp.get("rows", [])
        out = []
        for r in rows:
            out.append({
                "source": r[0] or "unknown",
                "views": int(r[1]) if len(r) > 1 else 0,
                "watch_minutes": int(r[2]) if len(r) > 2 else 0,
            })
        return {"available": True, "sources": out, "days": days}
    except Exception as exc:
        log.warning("traffic sources fetch failed: %s", exc)
        return {"available": False, "reason": str(exc)}


def fetch_geography(channel_id: int, days: int = 30) -> dict:
    """Fetch views by country."""
    yta = _yta_client(channel_id)
    if yta is None:
        return {"available": False, "reason": "YouTube not connected"}
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views,estimatedMinutesWatched,subscribersGained",
            dimensions="country",
            sort="-views",
            maxResults=20,
        ).execute()
        rows = resp.get("rows", [])
        out = []
        for r in rows:
            out.append({
                "country": r[0] or "unknown",
                "views": int(r[1]) if len(r) > 1 else 0,
                "watch_minutes": int(r[2]) if len(r) > 2 else 0,
                "subs_gained": int(r[3]) if len(r) > 3 else 0,
            })
        return {"available": True, "countries": out, "days": days}
    except Exception as exc:
        log.warning("geography fetch failed: %s", exc)
        return {"available": False, "reason": str(exc)}


def detect_anomalies(channel_id: int, threshold_pct: float = 2.0) -> list[dict]:
    """Detect sudden spikes or drops in views/subs.

    Compares each video's latest snapshot to its previous one. If the
    change exceeds `threshold_pct` (default 2x), it's flagged as an anomaly.
    """
    anomalies = []
    with session_scope() as db:
        videos = db.query(Video).filter_by(channel_id=channel_id,
                                            status="published").all()
        for v in videos:
            snaps = (db.query(AnalyticsSnapshot)
                     .filter_by(video_id=v.id)
                     .order_by(AnalyticsSnapshot.captured_at.desc())
                     .limit(2).all())
            if len(snaps) < 2:
                continue
            latest, prev = snaps[0], snaps[1]
            if prev.views == 0:
                continue
            change = (latest.views - prev.views) / prev.views
            if abs(change) >= threshold_pct:
                anomalies.append({
                    "video_id": v.id,
                    "title": v.title or v.topic,
                    "prev_views": prev.views,
                    "latest_views": latest.views,
                    "change_pct": round(change * 100, 1),
                    "type": "spike" if change > 0 else "drop",
                })
    return sorted(anomalies, key=lambda x: abs(x["change_pct"]), reverse=True)


async def analyze_comment_sentiment(video_id: int) -> dict:
    """Fetch the latest comments on a video and analyze their sentiment via LLM."""
    from . import llm
    from .uploader import _youtube_client
    with session_scope() as db:
        v = db.get(Video, video_id)
        if not v or not v.yt_video_id or v.yt_video_id.startswith("DRYRUN"):
            return {"available": False, "reason": "video not published"}
        channel_id = v.channel_id
        yt_id = v.yt_video_id
    yt = _youtube_client(channel_id)
    if yt is None:
        return {"available": False, "reason": "YouTube not connected"}
    try:
        resp = yt.commentThreads().list(
            part="snippet", videoId=yt_id, maxResults=20, order="relevance",
        ).execute()
        comments = []
        for item in resp.get("items", []):
            text = (item.get("snippet", {}).get("topLevelComment", {})
                    .get("snippet", {}).get("textOriginal", ""))
            if text:
                comments.append(text)
        if not comments:
            return {"available": True, "sentiment": "neutral",
                    "positive": 0, "neutral": 0, "negative": 0,
                    "total": 0}
        # Ask LLM to classify.
        prompt = [
            {"role": "system", "content": (
                "You are a sentiment analyzer. Given a list of YouTube comments, "
                "respond ONLY with JSON: {positive: int, neutral: int, negative: int, "
                "overall: 'positive'|'neutral'|'negative', summary: one sentence}."
            )},
            {"role": "user", "content": "\n".join(f"- {c}" for c in comments)},
        ]
        data = await llm.chat_json(prompt, temperature=0.3)
        if isinstance(data, dict):
            return {"available": True, **data, "total": len(comments)}
        return {"available": True, "sentiment": "neutral",
                "positive": 0, "neutral": len(comments), "negative": 0,
                "total": len(comments)}
    except Exception as exc:
        log.warning("comment sentiment failed: %s", exc)
        return {"available": False, "reason": str(exc)}
