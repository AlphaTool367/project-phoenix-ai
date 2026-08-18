"""Self-learning AI: turns analytics into strategy.

Nightly job compares each video's latest metrics with the channel baseline,
rewards the winning niches / hook styles / title patterns / publish hours and
penalizes the losers. The resulting StrategyProfile steers tomorrow's
research prompts, script hooks and schedule — a closed improvement loop.
"""
from __future__ import annotations

from datetime import datetime

from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, StrategyProfile, Video

log = get_logger("learning")

LR = 0.15  # learning rate per update


def _latest_snapshots(db, channel_id: int) -> dict[int, AnalyticsSnapshot]:
    snaps = (
        db.query(AnalyticsSnapshot)
        .filter(AnalyticsSnapshot.channel_id == channel_id)
        .order_by(AnalyticsSnapshot.captured_at.desc())
        .all()
    )
    latest: dict[int, AnalyticsSnapshot] = {}
    for s in snaps:
        if s.video_id is not None:
            latest.setdefault(s.video_id, s)
    return latest


def _perf(s: AnalyticsSnapshot) -> float:
    """Composite performance score."""
    return (
        min(s.views / 1000.0, 5.0)
        + s.retention_pct / 25.0
        + s.ctr_pct / 3.0
        + s.subs_gained / 20.0
    )


async def update_strategy(channel_id: int) -> dict:
    with session_scope() as db:
        profile = db.query(StrategyProfile).filter_by(channel_id=channel_id).first()
        if profile is None:
            profile = StrategyProfile(channel_id=channel_id)
            db.add(profile)
            db.flush()

        latest = _latest_snapshots(db, channel_id)
        if len(latest) < 2:
            profile.insights = (profile.insights or []) + [
                "Not enough data yet — publish a few more videos to start learning."
            ][-10:]
            return {"updated": False, "reason": "insufficient_data"}

        videos = {v.id: v for v in db.query(Video).filter(
            Video.id.in_(latest.keys())).all()}
        scores = {vid: _perf(s) for vid, s in latest.items()}
        baseline = sum(scores.values()) / len(scores)

        niche_w = dict(profile.niche_weights or {})
        hook_w = dict(profile.hook_weights or {})
        title_p = dict(profile.title_patterns or {})
        hour_w: dict[str, float] = {
            str(h): 1.0 for h in (profile.publish_hours or [13, 17, 21])
        }
        insights: list[str] = list(profile.insights or [])

        for vid, score in scores.items():
            v = videos.get(vid)
            if v is None:
                continue
            delta = LR * (1.0 if score >= baseline else -1.0)
            ctx = v.strategy_context or {}

            niche = v.niche or "unknown"
            niche_w[niche] = round(max(0.2, niche_w.get(niche, 1.0) + delta), 3)

            hook = ctx.get("hook_style")
            if hook:
                hook_w[hook] = round(max(0.2, hook_w.get(hook, 1.0) + delta), 3)

            if v.title:
                pattern = ("question" if v.title.rstrip().endswith("?")
                           else "number_list" if any(ch.isdigit() for ch in v.title[:12])
                           else "statement")
                title_p[pattern] = round(max(0.2, title_p.get(pattern, 1.0) + delta), 3)

            if v.published_at:
                hour_w[str(v.published_at.hour)] = round(
                    max(0.2, hour_w.get(str(v.published_at.hour), 1.0) + delta), 3)

            snap = latest[vid]
            if score >= baseline * 1.3:
                insights.append(
                    f"WIN: '{v.title[:50]}' ({niche}/{ctx.get('hook_style', '?')}) "
                    f"— {snap.views} views, {snap.retention_pct}% retention. Double down."
                )
            elif score <= baseline * 0.6:
                insights.append(
                    f"MISS: '{v.title[:50]}' underperformed "
                    f"(CTR {snap.ctr_pct}%) — rework hooks/thumbnails in this lane."
                )

        best_hours = sorted(hour_w, key=hour_w.get, reverse=True)[:3]
        profile.niche_weights = niche_w
        profile.hook_weights = hook_w
        profile.title_patterns = title_p
        profile.publish_hours = sorted(int(h) for h in best_hours)
        profile.insights = insights[-20:]
        profile.updated_at = datetime.utcnow()

        log.info("strategy updated for channel %d (baseline %.2f, %d videos)",
                 channel_id, baseline, len(scores))
        return {
            "updated": True,
            "baseline": round(baseline, 2),
            "niche_weights": niche_w,
            "hook_weights": hook_w,
            "publish_hours": profile.publish_hours,
        }


def strategy_context_for_prompt(profile: StrategyProfile | None) -> str:
    """Rendered into research/script prompts so the AI follows what it learned."""
    if not profile:
        return ""
    parts = []
    if profile.niche_weights:
        best = max(profile.niche_weights, key=profile.niche_weights.get)
        parts.append(f"best-performing niche so far: {best}")
    if profile.hook_weights:
        best_hook = max(profile.hook_weights, key=profile.hook_weights.get)
        parts.append(f"most effective hook style: {best_hook}")
    if profile.insights:
        parts.append("recent lessons: " + " | ".join(profile.insights[-3:]))
    return ("Channel learning context — " + "; ".join(parts)) if parts else ""
