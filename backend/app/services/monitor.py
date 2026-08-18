"""YouTube realtime monitor — discovers top videos in a niche and learns from them.

The monitor uses the YouTube Data API v3 (search.list + videos.list + channels.list)
to find the highest-viewed videos in a given niche, fetches their full metadata
(title, tags, description, statistics), and stores them in the TrendingVideo table.

When `settings.monitor_learn_from_top_videos` is True, an LLM call extracts
structured insights from each top video:
  - hook (the opening line / curiosity gap)
  - title_pattern (question? number-list? bold-claim?)
  - tag_cluster (the cluster of related tags)
  - description_pattern (paragraph structure, CTA placement)
  - duration_band (shorts / medium / long — which works best)

These insights are stored in the LearnedInsight table and fed back into the
scriptwriter / SEO / scheduler via learning.py.

Requires OAuth (the same token used for uploads). When not connected, the
monitor falls back to a built-in catalog so the dashboard still works.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp, parse_json_loose
from ..database import session_scope
from ..models import Channel, LearnedInsight, TrendingVideo
from . import llm
from .uploader import get_credentials

log = get_logger("monitor")


def _youtube_client(channel_id: int):
    """Build a YouTube Data API client for the channel's cached OAuth token."""
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def search_top_videos(
    channel_id: int,
    query: str | None = None,
    niches: list[str] | None = None,
    region_code: str | None = None,
    min_views: int | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Search YouTube for top videos matching the query / niches.

    Returns a list of dicts (the raw shape the API returns + a parsed view_count).
    Filters out videos below `min_views` (default: settings.monitor_min_views).
    """
    yt = _youtube_client(channel_id)
    if yt is None:
        log.warning("monitor: YouTube not connected for channel %d — returning []", channel_id)
        return []

    region = region_code or settings.monitor_region_code or "US"
    floor = min_views if min_views is not None else settings.monitor_min_views
    queries = []
    if query:
        queries = [query]
    elif niches:
        queries = list(niches)
    else:
        # Pull the channel's niche as a fallback.
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            if ch:
                queries = [ch.niche]
    if not queries:
        queries = ["technology"]

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    for q in queries:
        try:
            resp = yt.search().list(
                part="snippet",
                q=q,
                type="video",
                order="viewCount",          # sort by views — gets the top performers
                maxResults=min(max_results, 50),
                regionCode=region,
                relevanceLanguage="en",
                publishedAfter="2020-01-01T00:00:00Z",
            ).execute()
            ids = [it["id"]["videoId"] for it in resp.get("items", [])
                   if it.get("id", {}).get("videoId")]
            if not ids:
                continue
            # Fetch full statistics + content details for each video.
            stats = yt.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(ids),
            ).execute()
            for v in stats.get("items", []):
                vid = v.get("id")
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                stats_obj = v.get("statistics", {}) or {}
                snippet = v.get("snippet", {}) or {}
                cd = v.get("contentDetails", {}) or {}
                views = int(stats_obj.get("viewCount", 0) or 0)
                if views < floor:
                    continue
                duration_iso = cd.get("duration", "PT0S")
                duration_sec = _iso8601_to_seconds(duration_iso)
                published_raw = snippet.get("publishedAt", "")
                try:
                    published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                except Exception:
                    published = None
                thumbs = snippet.get("thumbnails", {}) or {}
                all_items.append({
                    "yt_video_id": vid,
                    "title": snippet.get("title", ""),
                    "niche": q,
                    "channel_title": snippet.get("channelTitle", ""),
                    "view_count": views,
                    "like_count": int(stats_obj.get("likeCount", 0) or 0),
                    "comment_count": int(stats_obj.get("commentCount", 0) or 0),
                    "duration_seconds": duration_sec,
                    "published_at": published,
                    "tags": snippet.get("tags", []) or [],
                    "description": snippet.get("description", "") or "",
                    "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
                    "region": region,
                })
        except Exception as exc:
            log.warning("monitor: search failed for query '%s': %s", q, exc)
            continue

    # Sort by views descending.
    all_items.sort(key=lambda x: x["view_count"], reverse=True)
    return all_items[:max_results]


def _iso8601_to_seconds(iso: str) -> float:
    """Convert ISO 8601 duration (PT#M#S) to seconds. Returns 0 on failure."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def store_trending_videos(channel_id: int, items: list[dict]) -> int:
    """Persist a list of trending video dicts into the TrendingVideo table.

    Updates view/like/comment counts if the row already exists. Returns the
    number of rows written/updated.
    """
    count = 0
    with session_scope() as db:
        for it in items:
            existing = db.query(TrendingVideo).filter_by(
                yt_video_id=it["yt_video_id"], channel_id=channel_id
            ).first()
            if existing:
                existing.view_count = it["view_count"]
                existing.like_count = it["like_count"]
                existing.comment_count = it["comment_count"]
                existing.fetched_at = datetime.utcnow()
                count += 1
                continue
            row = TrendingVideo(
                channel_id=channel_id,
                yt_video_id=it["yt_video_id"],
                title=clamp(it["title"], 500),
                niche=it.get("niche", ""),
                channel_title=it.get("channel_title", ""),
                view_count=it["view_count"],
                like_count=it.get("like_count", 0),
                comment_count=it.get("comment_count", 0),
                duration_seconds=it.get("duration_seconds", 0),
                published_at=it.get("published_at"),
                tags=it.get("tags", []),
                description=it.get("description", "")[:5000],
                thumbnail=it.get("thumbnail"),
                region=it.get("region", "US"),
                fetched_at=datetime.utcnow(),
                analyzed=False,
            )
            db.add(row)
            count += 1
    log.info("monitor: stored %d trending videos for channel %d", count, channel_id)
    return count


async def extract_insights(channel_id: int, max_videos: int = 10) -> int:
    """For each un-analyzed TrendingVideo, ask the LLM to extract insights.

    The LLM gets the title + description + tags and returns a JSON object with
    hook / title_pattern / tag_cluster / description_pattern / duration_band.
    Each piece is stored as a LearnedInsight row.
    """
    if not settings.monitor_learn_from_top_videos:
        return 0

    with session_scope() as db:
        rows = (db.query(TrendingVideo)
                .filter_by(channel_id=channel_id, analyzed=False)
                .order_by(TrendingVideo.view_count.desc())
                .limit(max_videos).all())
        if not rows:
            return 0
        # Detach into plain dicts so we can close the session before the LLM call.
        items = [{
            "id": r.id,
            "yt_video_id": r.yt_video_id,
            "title": r.title,
            "niche": r.niche,
            "view_count": r.view_count,
            "tags": list(r.tags or []),
            "description": r.description,
            "duration_seconds": r.duration_seconds,
        } for r in rows]

    count = 0
    for it in items:
        prompt = [
            {"role": "system", "content": (
                "You analyze viral YouTube videos to extract patterns a creator "
                "can learn from. Respond ONLY with JSON: {hook, title_pattern, "
                "tag_cluster, description_pattern, duration_band, takeaways}. "
                "hook = the curiosity-gap opening line (paraphrased, not copied). "
                "title_pattern = one of: question | number_list | bold_claim | "
                "mystery | how_to | vs | story. tag_cluster = 5-8 keyword tags. "
                "description_pattern = one of: question_first | summary_first | "
                "chapters_first | cta_first. duration_band = shorts | medium | long. "
                "takeaways = 2-3 short bullet strings of what makes this video work."
            )},
            {"role": "user", "content": (
                f"Title: {it['title']}\nNiche: {it['niche']}\nViews: {it['view_count']}\n"
                f"Duration: {it['duration_seconds']}s\n"
                f"Tags: {it['tags']}\nDescription: {it['description'][:1500]}"
            )},
        ]
        try:
            data = await llm.chat_json(prompt, temperature=0.4)
        except Exception as exc:
            log.warning("monitor: insight LLM call failed for %s: %s", it["yt_video_id"], exc)
            data = None
        if not isinstance(data, dict):
            # Mark as analyzed anyway so we don't retry forever.
            with session_scope() as db:
                row = db.get(TrendingVideo, it["id"])
                if row:
                    row.analyzed = True
            continue
        score = min(it["view_count"] / 1_000_000.0, 100.0)
        insights_to_add = [
            ("hook", str(data.get("hook", ""))),
            ("title_pattern", str(data.get("title_pattern", ""))),
            ("tag_cluster", ", ".join(data.get("tag_cluster", []) or [])),
            ("description_pattern", str(data.get("description_pattern", ""))),
            ("duration_band", str(data.get("duration_band", ""))),
        ]
        for take in (data.get("takeaways") or [])[:3]:
            insights_to_add.append(("takeaway", str(take)))
        with session_scope() as db:
            for itype, content in insights_to_add:
                if not content or content == "[]":
                    continue
                db.add(LearnedInsight(
                    channel_id=channel_id,
                    niche=it["niche"],
                    insight_type=itype,
                    content=clamp(content, 1000),
                    meta={"source_title": it["title"][:200], "views": it["view_count"]},
                    source_video_id=it["yt_video_id"],
                    score=score,
                ))
            row = db.get(TrendingVideo, it["id"])
            if row:
                row.analyzed = True
            count += 1
    log.info("monitor: extracted insights from %d videos for channel %d", count, channel_id)
    return count


async def search_and_learn(
    channel_id: int,
    query: str | None = None,
    niches: list[str] | None = None,
    region_code: str | None = None,
    min_views: int | None = None,
    max_results: int = 20,
    learn: bool = True,
) -> dict:
    """One-shot: search YouTube, store results, extract insights. Returns a summary."""
    items = search_top_videos(
        channel_id, query=query, niches=niches,
        region_code=region_code, min_views=min_views, max_results=max_results,
    )
    stored = store_trending_videos(channel_id, items)
    insights = 0
    if learn and settings.monitor_learn_from_top_videos and stored:
        insights = await extract_insights(channel_id, max_videos=min(10, stored))
    return {
        "found": len(items),
        "stored": stored,
        "insights_extracted": insights,
        "top_video": items[0] if items else None,
    }


def list_trending_videos(channel_id: int, niche: str | None = None,
                         limit: int = 50) -> list[dict]:
    """Return cached trending videos for the dashboard."""
    with session_scope() as db:
        q = db.query(TrendingVideo).filter_by(channel_id=channel_id)
        if niche:
            q = q.filter(TrendingVideo.niche == niche)
        rows = q.order_by(TrendingVideo.view_count.desc()).limit(limit).all()
        return [{
            "id": r.id,
            "yt_video_id": r.yt_video_id,
            "title": r.title,
            "niche": r.niche,
            "channel_title": r.channel_title,
            "view_count": r.view_count,
            "like_count": r.like_count,
            "comment_count": r.comment_count,
            "duration_seconds": r.duration_seconds,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "tags": list(r.tags or []),
            "thumbnail": r.thumbnail,
            "region": r.region,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            "analyzed": r.analyzed,
        } for r in rows]


def list_insights(channel_id: int, niche: str | None = None,
                  insight_type: str | None = None, limit: int = 100) -> list[dict]:
    """Return cached learned insights for the dashboard."""
    with session_scope() as db:
        q = db.query(LearnedInsight).filter_by(channel_id=channel_id)
        if niche:
            q = q.filter(LearnedInsight.niche == niche)
        if insight_type:
            q = q.filter(LearnedInsight.insight_type == insight_type)
        rows = q.order_by(LearnedInsight.score.desc(),
                          LearnedInsight.created_at.desc()).limit(limit).all()
        return [{
            "id": r.id,
            "niche": r.niche,
            "insight_type": r.insight_type,
            "content": r.content,
            "meta": r.meta,
            "source_video_id": r.source_video_id,
            "score": r.score,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]


def get_inspiration_for_niche(channel_id: int, niche: str, limit: int = 8) -> str:
    """Compose a short inspiration string for the scriptwriter from cached insights.

    Returns a multi-line string like:
      - hook: "What if everything you knew about X was wrong?"
      - title_pattern: question
      - tag_cluster: ai, future, technology, ...
      - takeaways: Open with a personal stake. Use a number in the title.
    """
    rows = list_insights(channel_id, niche=niche, limit=limit)
    if not rows:
        return ""
    by_type: dict[str, list[str]] = {}
    for r in rows:
        by_type.setdefault(r["insight_type"], []).append(r["content"])
    lines = []
    if by_type.get("hook"):
        lines.append("Proven hooks (paraphrase, don't copy):")
        for h in by_type["hook"][:3]:
            lines.append(f"  - {h}")
    if by_type.get("title_pattern"):
        from collections import Counter
        c = Counter(by_type["title_pattern"])
        top = c.most_common(1)[0][0]
        lines.append(f"Top title pattern in this niche: {top}")
    if by_type.get("tag_cluster"):
        lines.append("Trending tag clusters: " + " | ".join(by_type["tag_cluster"][:3]))
    if by_type.get("duration_band"):
        from collections import Counter
        c = Counter(by_type["duration_band"])
        top = c.most_common(1)[0][0]
        lines.append(f"Top duration band: {top}")
    if by_type.get("takeaway"):
        lines.append("Key takeaways:")
        for t in by_type["takeaway"][:3]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


def suggest_upload_times(channel_id: int) -> list[dict]:
    """Suggest the best upload hours based on cached insights + learning profile.

    Returns a list of {hour, score, reason} dicts.
    """
    from ..models import StrategyProfile
    with session_scope() as db:
        sp = db.query(StrategyProfile).filter_by(channel_id=channel_id).first()
        publish_hours = (sp.publish_hours if sp else None) or [13, 17, 21]
    return [{"hour": h, "score": 1.0, "reason": "channel learning"}
            for h in publish_hours]
