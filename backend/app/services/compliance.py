"""Compliance scoring — ad-friendly, made-for-kids, profanity, controversy.

Before publishing, the LLM scores each video on 4 compliance dimensions
that affect monetization:

  - **ad_friendliness** (0-100): how likely is this video to attract
    advertiser-friendly ads? Penalizes profanity, violence, adult themes,
    controversial topics.
  - **made_for_kids** (0-100): how likely is COPPA to flag this as
    made-for-kids? High scores mean the video WILL be flagged, which
    disables comments + personalized ads (huge revenue hit).
  - **demonetization_risk** (0-100): probability of getting demonetized.
    Combines ad_friendliness (inverted) + made_for_kids + topic sensitivity.
  - **controversy_level** (0-100): political/religious/social controversy.
    High controversy may attract engagement but scares advertisers.

Returns a single `compliance_score` (0-100) and a recommendation:
  'publish' / 'publish_with_warning' / 'review_manually' / 'do_not_publish'

Stored on the Video row via `seo_json.compliance_report`.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("compliance")


# Topics YouTube tends to demonetize. Used by the template fallback.
DEMONETIZATION_TOPICS = {
    "violence", "gore", "blood", "weapon", "gun", "knife", "kill", "murder",
    "terror", "war", "combat", "drug", "marijuana", "cocaine", "heroin",
    "alcohol", "drunk", "nude", "nudity", "sex", "sexual", "porn",
    "profanity", "swear", "fuck", "shit", "bitch",
    "terrorist", "extremist", "racist", "hate",
}

# Topics COPPA tends to flag as "made for kids".
KIDS_TOPICS = {
    "cartoon", "animation", "toy", "doll", "kid", "child", "baby",
    "playground", "school", "homework", "nursery", "rhyme", "fairy",
    "princess", "superhero", "lego", "minecraft", "roblox",
}


async def score_compliance(
    topic: str,
    niche: str,
    title: str,
    description: str,
    narration: str = "",
) -> dict:
    """Score a video on 4 compliance dimensions.

    Returns:
      {
        "ad_friendliness": int,        # 0-100 (higher = better)
        "made_for_kids": int,          # 0-100 (higher = MORE likely kids)
        "demonetization_risk": int,    # 0-100 (higher = riskier)
        "controversy_level": int,      # 0-100 (higher = more controversial)
        "compliance_score": int,       # 0-100 overall (higher = safer)
        "recommendation": str,         # publish / publish_with_warning / review_manually / do_not_publish
        "reasons": [str],              # what's wrong
        "engine": "llm" | "template",
      }
    """
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube compliance expert. Score the video on 4 "
            "dimensions (each 0-100):\n"
            "  - ad_friendliness: how likely to attract advertiser-friendly ads?\n"
            "  - made_for_kids: how likely is COPPA to flag this as made-for-kids?\n"
            "    (high score = will be flagged, which disables comments + personalized ads)\n"
            "  - demonetization_risk: probability of getting demonetized?\n"
            "  - controversy_level: political/religious/social controversy?\n"
            "Respond ONLY with JSON: {ad_friendliness, made_for_kids, "
            "demonetization_risk, controversy_level, reasons (array of short strings), "
            "recommendation (one of: publish, publish_with_warning, review_manually, do_not_publish)}."
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\nNiche: {niche}\nTitle: {title}\n"
            f"Description: {description[:500]}\n"
            f"Narration excerpt: {narration[:500]}"
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.3)
    except Exception as exc:
        log.warning("compliance LLM call failed: %s", exc)
        data = None

    if isinstance(data, dict) and "ad_friendliness" in data:
        return _format_llm_result(data)

    return _template_compliance(topic, niche, title, description, narration)


def _safe_int(v: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 50


def _format_llm_result(data: dict) -> dict:
    ad = _safe_int(data.get("ad_friendliness"))
    kids = _safe_int(data.get("made_for_kids"))
    risk = _safe_int(data.get("demonetization_risk"))
    controv = _safe_int(data.get("controversy_level"))
    # Overall = ad_friendliness weighted heaviest, then penalize risk + kids + controversy.
    overall = max(0, min(100, int(
        ad * 0.5
        + (100 - risk) * 0.25
        + (100 - kids) * 0.15
        + (100 - controv) * 0.10
    )))
    rec = str(data.get("recommendation", "publish_with_warning")).lower().strip()
    if rec not in ("publish", "publish_with_warning", "review_manually", "do_not_publish"):
        # Infer from the scores.
        if overall >= 80:
            rec = "publish"
        elif overall >= 60:
            rec = "publish_with_warning"
        elif overall >= 40:
            rec = "review_manually"
        else:
            rec = "do_not_publish"
    return {
        "ad_friendliness": ad,
        "made_for_kids": kids,
        "demonetization_risk": risk,
        "controversy_level": controv,
        "compliance_score": overall,
        "recommendation": rec,
        "reasons": [clamp(str(r), 200) for r in (data.get("reasons") or [])][:5],
        "engine": "llm",
    }


def _template_compliance(topic: str, niche: str, title: str,
                         description: str, narration: str) -> dict:
    """Heuristic fallback when the LLM is unavailable."""
    text = f"{topic} {niche} {title} {description} {narration}".lower()
    words = set(text.split())

    # Check for demonetization-triggering words.
    demo_hits = words & DEMONETIZATION_TOPICS
    # Check for kids-targeting words.
    kids_hits = words & KIDS_TOPICS

    ad = 95 - (len(demo_hits) * 15)
    kids = 30 + (len(kids_hits) * 20)
    risk = 5 + (len(demo_hits) * 20)
    controv = 10 + (15 if any(w in text for w in ("politic", "religion", "election")) else 0)

    ad = max(0, min(100, ad))
    kids = max(0, min(100, kids))
    risk = max(0, min(100, risk))
    controv = max(0, min(100, controv))

    overall = max(0, min(100, int(
        ad * 0.5 + (100 - risk) * 0.25 + (100 - kids) * 0.15 + (100 - controv) * 0.10
    )))
    if overall >= 80:
        rec = "publish"
    elif overall >= 60:
        rec = "publish_with_warning"
    elif overall >= 40:
        rec = "review_manually"
    else:
        rec = "do_not_publish"

    reasons = []
    if demo_hits:
        reasons.append(f"contains demonetization-triggering terms: {', '.join(list(demo_hits)[:5])}")
    if kids_hits:
        reasons.append(f"may be flagged as made-for-kids (COPPA): {', '.join(list(kids_hits)[:5])}")
    if not reasons:
        reasons.append("no compliance issues detected by heuristic")

    return {
        "ad_friendliness": ad,
        "made_for_kids": kids,
        "demonetization_risk": risk,
        "controversy_level": controv,
        "compliance_score": overall,
        "recommendation": rec,
        "reasons": reasons,
        "engine": "template",
    }
