"""Competitor monitoring + A/B testing + smart re-upload.

Phase 4 features for long-term channel growth:

  - **Competitor monitoring**: track up to N competitor channels by ID.
    Fetch their latest videos + stats, store in CompetitorChannel +
    CompetitorVideo tables, and surface "they published X hours ago,
    here's what worked" insights.

  - **A/B title + thumbnail testing**: when a video is published, the
    engine generates 2-3 alternative titles + thumbnails. After a
    configurable time window (default 7 days), if the active variant's
    CTR is below the channel's average, the engine swaps to the
    runner-up. (The YouTube API doesn't expose per-variant CTR, so we
    use the LLM's CTR prediction as a proxy.)

  - **Smart re-upload**: when a video underperforms (e.g. <50% of the
    channel's average views after 14 days), the engine suggests a
    new title + thumbnail + tags. With the user's approval, it updates
    the video's metadata via the YouTube API (no re-upload needed).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, Video
from .uploader import get_credentials

log = get_logger("growth")


def _yt_client(channel_id: int):
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ----------------------------------------------------------------- competitors

def add_competitor(channel_id: int, competitor_yt_id: str,
                   label: str = "") -> dict:
    """Add a competitor channel to monitor. Stores it in the DB."""
    from ..models import CompetitorChannel
    with session_scope() as db:
        existing = db.query(CompetitorChannel).filter_by(
            channel_id=channel_id, yt_channel_id=competitor_yt_id).first()
        if existing:
            return {"added": False, "reason": "already tracked",
                    "id": existing.id}
        c = CompetitorChannel(
            channel_id=channel_id,
            yt_channel_id=competitor_yt_id,
            label=label,
        )
        db.add(c)
        db.flush()
        return {"added": True, "id": c.id, "yt_channel_id": competitor_yt_id}


def list_competitors(channel_id: int) -> list[dict]:
    from ..models import CompetitorChannel
    with session_scope() as db:
        rows = db.query(CompetitorChannel).filter_by(channel_id=channel_id).all()
        return [{"id": r.id, "yt_channel_id": r.yt_channel_id,
                 "label": r.label, "last_synced_at": r.last_synced_at.isoformat()
                 if r.last_synced_at else None}
                for r in rows]


def remove_competitor(channel_id: int, competitor_id: int) -> dict:
    from ..models import CompetitorChannel
    with session_scope() as db:
        c = db.get(CompetitorChannel, competitor_id)
        if not c or c.channel_id != channel_id:
            return {"removed": False, "reason": "not found"}
        db.delete(c)
        return {"removed": True, "id": competitor_id}


def sync_competitor_videos(channel_id: int, competitor_id: int) -> dict:
    """Fetch the competitor's most recent videos + stats."""
    from ..models import CompetitorChannel, CompetitorVideo
    with session_scope() as db:
        comp = db.get(CompetitorChannel, competitor_id)
        if not comp or comp.channel_id != channel_id:
            return {"synced": 0, "reason": "competitor not found"}
        comp_yt_id = comp.yt_channel_id

    yt = _yt_client(channel_id)
    if yt is None:
        return {"synced": 0, "reason": "YouTube not connected"}

    try:
        # Get the competitor's uploads playlist id.
        resp = yt.channels().list(part="contentDetails,snippet",
                                   id=comp_yt_id).execute()
        items = resp.get("items", [])
        if not items:
            return {"synced": 0, "reason": "channel not found"}
        uploads_playlist = (items[0].get("contentDetails", {})
                            .get("relatedPlaylists", {}).get("uploads"))
        channel_title = items[0].get("snippet", {}).get("title", "")

        # Fetch the latest 10 videos from the uploads playlist.
        resp = yt.playlistItems().list(part="snippet",
                                        playlistId=uploads_playlist,
                                        maxResults=10).execute()
        video_ids = [it["snippet"]["resourceId"]["videoId"]
                     for it in resp.get("items", [])
                     if it.get("snippet", {}).get("resourceId", {}).get("videoId")]
        if not video_ids:
            return {"synced": 0, "reason": "no videos found"}

        # Fetch statistics for each video.
        stats_resp = yt.videos().list(part="statistics,snippet",
                                       id=",".join(video_ids)).execute()
        count = 0
        with session_scope() as db:
            for v in stats_resp.get("items", []):
                vid = v.get("id")
                if not vid:
                    continue
                snip = v.get("snippet", {}) or {}
                stat = v.get("statistics", {}) or {}
                # Upsert.
                existing = db.query(CompetitorVideo).filter_by(
                    competitor_id=competitor_id, yt_video_id=vid).first()
                if existing:
                    existing.view_count = int(stat.get("viewCount", 0) or 0)
                    existing.like_count = int(stat.get("likeCount", 0) or 0)
                    existing.comment_count = int(stat.get("commentCount", 0) or 0)
                    existing.fetched_at = datetime.utcnow()
                else:
                    db.add(CompetitorVideo(
                        competitor_id=competitor_id,
                        yt_video_id=vid,
                        title=snip.get("title", ""),
                        channel_title=channel_title,
                        published_at=datetime.fromisoformat(
                            snip.get("publishedAt", "").replace("Z", "+00:00")
                        ) if snip.get("publishedAt") else None,
                        view_count=int(stat.get("viewCount", 0) or 0),
                        like_count=int(stat.get("likeCount", 0) or 0),
                        comment_count=int(stat.get("commentCount", 0) or 0),
                        fetched_at=datetime.utcnow(),
                    ))
                count += 1
            comp = db.get(CompetitorChannel, competitor_id)
            if comp:
                comp.last_synced_at = datetime.utcnow()
        return {"synced": count, "competitor_id": competitor_id,
                "channel_title": channel_title}
    except Exception as exc:
        log.warning("competitor sync failed: %s", exc)
        return {"synced": 0, "reason": str(exc)}


def list_competitor_videos(competitor_id: int, limit: int = 20) -> list[dict]:
    from ..models import CompetitorVideo
    with session_scope() as db:
        rows = (db.query(CompetitorVideo)
                .filter_by(competitor_id=competitor_id)
                .order_by(CompetitorVideo.view_count.desc())
                .limit(limit).all())
        return [{"id": r.id, "yt_video_id": r.yt_video_id,
                 "title": r.title, "channel_title": r.channel_title,
                 "view_count": r.view_count, "like_count": r.like_count,
                 "comment_count": r.comment_count,
                 "published_at": r.published_at.isoformat() if r.published_at else None}
                for r in rows]


# ----------------------------------------------------------------- A/B testing

async def suggest_title_alternatives(video: Video, count: int = 3) -> list[str]:
    """Ask the LLM to suggest alternative titles for a video.

    Used for A/B testing — the engine picks the best one based on the
    channel's learned title_patterns.
    """
    from . import llm
    from ..core.utils import clamp
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube title optimization expert. Given a video's "
            "current title + topic + niche, suggest 3 alternative titles that "
            "might perform better. Each title must be ≤95 chars, keyword "
            "front-loaded, no clickbait lies. Respond ONLY with a JSON array "
            "of strings."
        )},
        {"role": "user", "content": (
            f"Topic: {video.topic}\nNiche: {video.niche}\n"
            f"Current title: {video.title or video.topic}"
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.7)
        if isinstance(data, list):
            return [clamp(str(t), 95) for t in data if t][:count]
    except Exception as exc:
        log.warning("title alternatives LLM call failed: %s", exc)
    return []


# ----------------------------------------------------------------- smart re-upload

def find_underperforming_videos(channel_id: int, days: int = 14,
                                 threshold_pct: float = 0.5) -> list[dict]:
    """Find videos that underperformed the channel average after `days`.

    A video is "underperforming" if its first-`days` views are less than
    `threshold_pct` (default 50%) of the channel's average first-`days` views.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    with session_scope() as db:
        videos = (db.query(Video)
                  .filter(Video.channel_id == channel_id,
                          Video.status == "published",
                          Video.published_at < cutoff)
                  .all())
        if not videos:
            return []
        # Compute each video's first-`days` views.
        vids_with_views: list[tuple[Video, int]] = []
        for v in videos:
            first_snap = (db.query(AnalyticsSnapshot)
                          .filter(AnalyticsSnapshot.video_id == v.id,
                                  AnalyticsSnapshot.captured_at <=
                                  (v.published_at + timedelta(days=days)))
                          .order_by(AnalyticsSnapshot.captured_at.desc())
                          .first())
            views = first_snap.views if first_snap else 0
            vids_with_views.append((v, views))
        if not vids_with_views:
            return []
        avg_views = sum(views for _, views in vids_with_views) / len(vids_with_views)
        under = [(v, views) for v, views in vids_with_views
                 if views < avg_views * threshold_pct]
        return [{
            "video_id": v.id,
            "title": v.title or v.topic,
            "views": views,
            "channel_avg": int(avg_views),
            "threshold": int(avg_views * threshold_pct),
            "yt_video_id": v.yt_video_id,
            "published_at": v.published_at.isoformat() if v.published_at else None,
        } for v, views in under]


async def suggest_metadata_overhaul(video: Video) -> dict:
    """Suggest new title + tags + description for an underperforming video."""
    from . import llm
    from ..core.utils import clamp
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube SEO expert. The current video is underperforming. "
            "Suggest a complete metadata overhaul: new title, new tags (≤14), "
            "new short description (≤500 chars). Respond ONLY with JSON: "
            "{title, tags (array), description}."
        )},
        {"role": "user", "content": (
            f"Topic: {video.topic}\nNiche: {video.niche}\n"
            f"Current title: {video.title}\n"
            f"Current tags: {video.tags}\n"
            f"Current description: {(video.description or '')[:500]}"
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.6)
        if isinstance(data, dict):
            return {
                "title": clamp(str(data.get("title", video.title or "")), 95),
                "tags": [str(t) for t in data.get("tags", [])][:14],
                "description": clamp(str(data.get("description", "")), 4500),
                "engine": "llm",
            }
    except Exception as exc:
        log.warning("metadata overhaul LLM call failed: %s", exc)
    return {"title": video.title, "tags": video.tags,
            "description": video.description, "engine": "fallback"}


def apply_metadata_update(channel_id: int, video_yt_id: str,
                          title: str, description: str,
                          tags: list[str]) -> dict:
    """Update a published video's metadata via the YouTube API."""
    yt = _yt_client(channel_id)
    if yt is None:
        return {"updated": False, "reason": "YouTube not connected"}
    try:
        body = {
            "id": video_yt_id,
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "27",
                "defaultLanguage": "en",
            },
        }
        yt.videos().update(part="snippet", body=body).execute()
        log.info("updated metadata for video %s", video_yt_id)
        return {"updated": True, "video_id": video_yt_id}
    except Exception as exc:
        log.warning("metadata update failed: %s", exc)
        return {"updated": False, "reason": str(exc)}
