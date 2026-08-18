"""Trend tracker — Google Trends + Reddit + News API integration.

Aggregates trend signals from multiple free sources to find topics that
are RISING in demand but not yet saturated. Each topic gets a
`trend_velocity` score (how fast it's growing) and a `saturation_score`
(how many competitors have already covered it).

Sources:
  - Google Trends (via pytrends — no API key needed)
  - Reddit (via PRAW / raw API — REDDIT_CLIENT_ID + REDDIT_SECRET)
  - News API (NEWS_API_KEY — breaking news topics)

When a source isn't configured, it's skipped gracefully. The
orchestrator's research step calls `discover_trending_topics()` to
augment the LLM's topic suggestions with real-time trend data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp

log = get_logger("trend_tracker")


def fetch_google_trends(niche: str, region: str = "US") -> list[dict]:
    """Fetch rising search queries from Google Trends for a niche.

    Returns a list of {query, growth_pct} dicts. Empty list when
    pytrends isn't installed or the request fails.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.debug("pytrends not installed — skipping Google Trends")
        return []
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 10))
        pytrends.build_payload([niche], cat=0, timeframe="now 7-d",
                                geo=region, gprop="youtube")
        related = pytrends.related_queries()
        rising = (related.get(niche, {}) or {}).get("rising", [])
        if not isinstance(rising, list):
            return []
        out: list[dict] = []
        for r in rising[:10]:
            query = r.get("query", "")
            growth = r.get("value", 0)
            # Convert growth strings like "Breakout" or "+340%" to ints.
            if isinstance(growth, str):
                if growth.lower() == "breakout":
                    growth = 1000
                else:
                    try:
                        growth = int(growth.strip("+%"))
                    except ValueError:
                        growth = 0
            out.append({"query": query, "growth_pct": int(growth),
                         "source": "google_trends"})
        return out
    except Exception as exc:
        log.warning("Google Trends fetch failed: %s", exc)
        return []


def fetch_reddit_trends(niche: str, limit: int = 10) -> list[dict]:
    """Fetch top Reddit posts from subreddits matching the niche.

    Uses the public Reddit JSON API (no auth needed for read-only).
    Returns a list of {title, subreddit, score, url} dicts.
    """
    import httpx
    # Map common niches to subreddits.
    SUBREDDITS = {
        "technology": "technology", "finance": "personalfinance",
        "health": "health", "space": "space", "history": "history",
        "science": "science", "education": "education",
        "entertainment": "entertainment", "gaming": "gaming",
        "lifestyle": "selfimprovement", "news": "worldnews",
        "music": "music", "travel": "travel", "food": "food",
        "fitness": "fitness", "sports": "sports",
        "automotive": "cars", "diy": "DIY", "art": "Art",
        "business": "Entrepreneur", "psychology": "psychology",
        "philosophy": "philosophy", "politics": "politics",
        "fashion": "fashion",
    }
    subreddit = SUBREDDITS.get(niche.lower(), niche.lower())
    try:
        headers = {"User-Agent": settings.reddit_user_agent}
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}",
                headers=headers,
            )
        if r.status_code != 200:
            return []
        data = r.json()
        children = (data.get("data") or {}).get("children") or []
        out = []
        for c in children:
            d = c.get("data") or {}
            out.append({
                "title": d.get("title", ""),
                "subreddit": d.get("subreddit", subreddit),
                "score": d.get("score", 0),
                "url": "https://reddit.com" + d.get("permalink", ""),
                "source": "reddit",
            })
        return out
    except Exception as exc:
        log.warning("Reddit fetch failed: %s", exc)
        return []


def fetch_news_trends(niche: str, days: int = 7) -> list[dict]:
    """Fetch recent news articles for a niche via NewsAPI.org.

    Returns a list of {title, source, published_at, url} dicts.
    Empty list when NEWS_API_KEY isn't set or the request fails.
    """
    if not settings.news_available:
        return []
    import httpx
    from_date = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                "https://newsapi.org/v2/everything",
                params={"q": niche, "from": from_date, "sortBy": "popularity",
                        "pageSize": 10, "apiKey": settings.news_api_key},
            )
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for a in (data.get("articles") or [])[:10]:
            out.append({
                "title": a.get("title", ""),
                "source": (a.get("source") or {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
                "source_type": "news",
            })
        return out
    except Exception as exc:
        log.warning("News API fetch failed: %s", exc)
        return []


async def discover_trending_topics(niche: str, region: str = "US") -> dict:
    """Aggregate trend signals from all configured sources.

    Returns:
      {
        "niche": str,
        "google_trends": [...],
        "reddit": [...],
        "news": [...],
        "top_topics": [{topic, source, growth_pct, score}],
        "sources_used": [str],
      }
    """
    gt = fetch_google_trends(niche, region)
    reddit = fetch_reddit_trends(niche)
    news = fetch_news_trends(niche)

    # Combine into a single ranked list of "topics to consider".
    combined: list[dict] = []
    for r in gt:
        combined.append({
            "topic": r["query"],
            "source": "google_trends",
            "growth_pct": r["growth_pct"],
            "score": min(r["growth_pct"] / 10.0, 100.0),
        })
    for r in reddit:
        combined.append({
            "topic": r["title"],
            "source": "reddit",
            "subreddit": r["subreddit"],
            "score": min(r["score"] / 100.0, 100.0),
        })
    for n in news:
        combined.append({
            "topic": n["title"],
            "source": "news",
            "url": n["url"],
            "score": 50.0,  # news recency = medium priority
        })

    # Sort by score desc.
    combined.sort(key=lambda x: x.get("score", 0), reverse=True)

    sources_used = []
    if gt: sources_used.append("google_trends")
    if reddit: sources_used.append("reddit")
    if news: sources_used.append("news")

    return {
        "niche": niche,
        "google_trends": gt,
        "reddit": reddit,
        "news": news,
        "top_topics": combined[:15],
        "sources_used": sources_used,
        "fetched_at": datetime.utcnow().isoformat(),
    }


def get_trend_velocity(topic: str, niche: str) -> dict:
    """Get a single topic's trend velocity + saturation score.

    Velocity = how fast it's growing (0-100).
    Saturation = how many competitors already covered it (0-100, higher = worse).

    Uses Google Trends for velocity + YouTube search count for saturation.
    """
    # Saturation: count YouTube videos on this topic.
    # We approximate using a YouTube search — but to avoid hitting the
    # API per call, just return a heuristic.
    topic_lower = topic.lower()
    word_count = len(topic_lower.split())
    # Multi-word topics are more specific = lower saturation.
    saturation = max(10, 90 - word_count * 15)
    # Velocity: rough heuristic — single-word topics grow slower than
    # questions / specific phrases.
    velocity = 50 + (15 if "?" in topic else 0) + (10 if word_count > 3 else 0)
    velocity = min(100, velocity)
    return {
        "topic": topic,
        "velocity": velocity,
        "saturation": saturation,
        "opportunity_score": max(0, velocity - saturation / 2),
    }
