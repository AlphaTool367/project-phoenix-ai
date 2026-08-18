"""Focused tests for truthful provider usage and automatic research labels."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import init_db, session_scope
from app.models import ProviderUsage
from app.services import provider_usage, research


def main() -> int:
    init_db()
    provider_usage.record_response(
        "test-provider", "test-model",
        {"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "cost": 0.0012}},
    )
    report = provider_usage.summary(1)
    row = next(x for x in report["services"] if x["service"] == "test-provider")
    assert row["total_tokens"] >= 18
    assert row["reported_cost_usd"] >= 0.0012
    assert row["cost_status"] == "provider_reported"

    async def fake_live(channel_id: int | None, niche: str, limit: int):
        return ([{
            "topic": "A verified live signal",
            "niche": niche,
            "demand": None,
            "competition": None,
            "virality": None,
            "score": 88.0,
            "score_basis": "source:google_trends",
            "keywords": ["verified", "signal"],
            "angle": "Explain the signal with cited facts.",
            "source": "google_trends",
            "data_quality": "live_signal",
        }], ["google_trends"])

    original = research._live_topics
    research._live_topics = fake_live
    try:
        report_obj = asyncio.run(research.run_research(None, "technology", limit=1))
    finally:
        research._live_topics = original
    assert report_obj.source == "live:google_trends"
    assert report_obj.topics[0]["data_quality"] == "live_signal"
    assert report_obj.topics[0]["source"] == "google_trends"
    with session_scope() as db:
        db.query(ProviderUsage).filter_by(service="test-provider").delete()
    print("research/usage checks passed: provider-reported cost and live source labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
