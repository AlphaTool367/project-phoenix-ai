"""AI trend & market research.

Discovers trending topics, scores demand vs competition, picks the best niche
and writes a TrendReport the scheduler uses as today's content strategy.

Live mode  : asks the configured LLM for a data-driven analysis.
Mock mode  : seeded generator over a built-in niche/topic catalog.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import date, datetime

from ..core.logging import get_logger
from ..core.utils import clamp
from ..database import session_scope
from ..models import StrategyProfile, TrendReport

log = get_logger("research")

# Built-in catalog used in mock mode and as LLM grounding context.
NICHE_CATALOG: dict[str, list[str]] = {
    "technology": [
        "AI tools that replace a full-time job", "The dark side of quantum computing",
        "Why everyone is switching to local LLMs", "5 futuristic gadgets you can buy now",
        "How neural implants actually work", "The robot that learned to cook",
    ],
    "finance": [
        "How compound interest quietly makes millionaires", "The psychology of market crashes",
        "Why index funds beat 90% of professionals", "Digital currencies explained simply",
        "The hidden math of renting vs buying", "How inflation silently eats your savings",
    ],
    "health": [
        "What 10 minutes of morning sunlight does to your brain",
        "The science of deep sleep", "Why walking beats the gym for longevity",
        "Gut bacteria and your mood", "The truth about intermittent fasting",
    ],
    "space": [
        "What Voyager 1 just sent back", "Why Mars dust is a nightmare for engineers",
        "The James Webb image that broke astronomy", "How SpaceX lands a rocket backwards",
        "The mystery of fast radio bursts",
    ],
    "history": [
        "The empire that vanished overnight", "Why Rome's concrete still stands",
        "The map that rewrote history", "A medieval invention ahead of its time",
        "The day the library of Alexandria burned",
    ],
    "science": [
        "Why time might not be real", "The paradox hiding in your DNA",
        "How glow-in-the-dark sharks were discovered", "The physics of black holes, simply",
        "Why placebo effects are getting stronger",
    ],
}


def _mock_topics(niches: list[str], day_seed: str, limit: int) -> list[dict]:
    """Deterministic-but-daily-varying synthetic trend scores."""
    seed = int(hashlib.sha256(day_seed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    topics: list[dict] = []
    for niche in niches:
        for t in NICHE_CATALOG.get(niche, [])[:4]:
            demand = rng.uniform(45, 98)
            competition = rng.uniform(15, 90)
            virality = rng.uniform(30, 95)
            score = round(demand * virality / max(competition, 5), 2)
            topics.append({
                "topic": t,
                "niche": niche,
                "demand": round(demand, 1),
                "competition": round(competition, 1),
                "virality": round(virality, 1),
                "score": score,
                "keywords": [w for w in t.lower().split() if len(w) > 4][:4],
                "angle": "explainer with a curiosity-gap hook",
            })
    topics.sort(key=lambda x: x["score"], reverse=True)
    return topics[:limit]


async def _live_topics(channel_id: int | None, niche: str, limit: int) -> tuple[list[dict], list[str]]:
    """Collect real trend signals without blocking the event loop.

    Scores are source scores or explicitly derived normalized values; they are
    never presented as YouTube views or provider balances.
    """
    from . import monitor, trend_tracker

    # trend_tracker performs synchronous network calls internally; isolate it
    # from FastAPI/scheduler's event loop.
    signal = await asyncio.to_thread(
        lambda: asyncio.run(trend_tracker.discover_trending_topics(niche))
    )
    sources = list(signal.get("sources_used") or [])
    topics: list[dict] = []
    seen: set[str] = set()
    for item in signal.get("top_topics") or []:
        title = str(item.get("topic", "")).strip()
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        topics.append({
            "topic": clamp(title, 120),
            "niche": niche,
            "demand": None,
            "competition": None,
            "virality": None,
            "score": round(float(item.get("score", 0) or 0), 2),
            "score_basis": f"source:{item.get('source', 'unknown')}",
            "keywords": [w for w in title.lower().split() if len(w) > 4][:6],
            "angle": "Explain the current signal in plain language; verify facts before publishing.",
            "source": item.get("source", "trend_signal"),
            "data_quality": "live_signal",
        })

    if channel_id:
        try:
            youtube_items = await asyncio.to_thread(
                monitor.search_top_videos,
                channel_id,
                query=niche,
                max_results=min(limit, 20),
            )
        except Exception as exc:
            log.warning("research: YouTube signal fetch failed: %s", exc)
            youtube_items = []
        if youtube_items:
            sources.append("youtube")
            max_views = max(int(x.get("view_count", 0) or 0) for x in youtube_items) or 1
            for item in youtube_items:
                title = str(item.get("title", "")).strip()
                key = title.casefold()
                if not title or key in seen:
                    continue
                seen.add(key)
                views = int(item.get("view_count", 0) or 0)
                topics.append({
                    "topic": clamp(title, 120),
                    "niche": niche,
                    "demand": None,
                    "competition": None,
                    "virality": None,
                    "score": round(100.0 * views / max_views, 2),
                    "score_basis": "normalized_youtube_views",
                    "keywords": list(item.get("tags", []))[:6],
                    "angle": "Study the public title and audience signal; create an original, non-copied angle.",
                    "source": "youtube",
                    "source_video_id": item.get("yt_video_id"),
                    "source_views": views,
                    "data_quality": "live_signal",
                })
    # Keep the strongest source-derived signals first.
    topics.sort(key=lambda x: float(x.get("score", 0) or 0), reverse=True)
    return topics[:limit], sorted(set(sources))


async def run_research(
    channel_id: int | None,
    niche_hint: str,
    language: str = "en",
    limit: int = 10,
) -> TrendReport:
    """Produce today's scored trend report and persist it."""
    from . import llm

    today = date.today().isoformat()
    strategy = None
    with session_scope() as db:
        if channel_id:
            strategy = db.get(StrategyProfile, channel_id)
            if strategy is None:
                strategy = StrategyProfile(channel_id=channel_id)
                db.add(strategy)
                db.flush()

    niche_weights = dict(strategy.niche_weights) if strategy else {}
    candidate_niches = sorted(
        set([niche_hint, *NICHE_CATALOG.keys()]),
        key=lambda n: niche_weights.get(n, 1.0),
        reverse=True,
    )[:4]

    topics: list[dict] | None = None
    source = "template_fallback"

    # Prefer real trend signals. This call is automatic and non-blocking at the
    # boundary; an unavailable provider simply contributes no signal.
    try:
        live_topics, live_sources = await _live_topics(channel_id, niche_hint, limit)
    except Exception as exc:
        log.warning("research: live signal collection failed: %s", exc)
        live_topics, live_sources = [], []

    if live_topics:
        topics = live_topics
        source = "live:" + ",".join(live_sources)

    if topics is None:
        strategy_note = ""
        if strategy and strategy.insights:
            strategy_note = "Learned insights to respect: " + "; ".join(strategy.insights[-5:])
        prompt = [
            {"role": "system", "content": (
                "You are a YouTube growth analyst. Respond ONLY with a JSON array of "
                "topic objects: topic, niche, demand (0-100), competition (0-100), "
                "virality (0-100), keywords (array), angle (one line). "
                "Favor high demand + low competition + high viral potential."
            )},
            {"role": "user", "content": (
                f"Today is {today}. Channel niche focus: {niche_hint}. "
                f"Also consider adjacent niches: {', '.join(candidate_niches)}. "
                f"Language: {language}. {strategy_note} "
                f"Give {limit} trending video topics for today with realistic scores."
            )},
        ]
        data = await llm.chat_json(prompt, temperature=0.7)
        if isinstance(data, list) and data:
            topics = []
            for t in data[:limit]:
                try:
                    demand = float(t.get("demand", 50))
                    competition = max(float(t.get("competition", 50)), 5)
                    virality = float(t.get("virality", 50))
                    topics.append({
                        "topic": clamp(str(t.get("topic", "Untitled")), 120),
                        "niche": str(t.get("niche", niche_hint))[:60],
                        "demand": demand, "competition": competition,
                        "virality": virality,
                        "score": round(demand * virality / competition, 2),
                        "keywords": [str(k) for k in t.get("keywords", [])][:6],
                        "angle": str(t.get("angle", ""))[:200],
                    })
                except (TypeError, ValueError):
                    continue
            topics.sort(key=lambda x: x["score"], reverse=True)
            source = "llm_suggestions"
            for item in topics:
                item["data_quality"] = "llm_suggestion_not_live_trend"
                item["score_basis"] = "llm_estimate"

    if not topics:
        topics = _mock_topics(candidate_niches, f"{today}-{niche_hint}", limit)
        for item in topics:
            item["data_quality"] = "template_fallback_not_live_trend"
            item["score_basis"] = "deterministic_template"
        source = "template_fallback"

    winning = max(topics, key=lambda t: t["score"])["niche"] if topics else niche_hint

    with session_scope() as db:
        report = TrendReport(
            channel_id=channel_id, date=today, topics=topics,
            winning_niche=winning, source=source,
        )
        db.add(report)
        db.flush()
        db.refresh(report)
        log.info(
            "trend research complete (%s): %d topics, winning niche '%s'",
            source, len(topics), winning,
        )
        return report
