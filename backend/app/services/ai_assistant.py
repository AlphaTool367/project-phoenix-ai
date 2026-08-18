"""AI Assistant — natural language video creation + chatbot.

Lets the user create videos and query channel data via natural language:
  - "Make a 5-minute video about quantum computing"
  - "How's my channel doing?"
  - "What should I make next?"

The assistant parses the user's intent, calls the right service, and
returns a human-readable response.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.logging import get_logger
from ..database import session_scope
from ..models import Channel, Video
from . import llm

log = get_logger("ai_assistant")


async def chat(channel_id: int, message: str) -> dict:
    """Process a natural language message from the user.

    Returns:
      {response: str, action: str|None, action_data: dict|None}

    The `action` field tells the frontend what to do (e.g. "produce_video",
    "show_analytics", "show_revenue"). The `action_data` field carries the
    parameters for that action.
    """
    msg = message.lower().strip()

    # ----- intent: produce a video -----
    produce_patterns = [
        r"(?:make|create|produce|generate)\s+(?:a\s+)?(?:video|short|long video)\s+(?:about|on|re:)\s+(.+)",
        r"(?:make|create|produce)\s+(?:a\s+)?(\d+\s*(?:min|minute|second|sec))\s+(?:video\s+)?(?:about|on)\s+(.+)",
    ]
    for pat in produce_patterns:
        m = re.search(pat, msg)
        if m:
            topic = m.group(2) if len(m.groups()) > 1 else m.group(1)
            length = "long" if "long" in msg or "min" in msg else "shorts" if "short" in msg else "manual"
            return {
                "response": f"I'll create a {length} video about '{topic}'. Starting production now…",
                "action": "produce_video",
                "action_data": {"topic": topic.strip(), "length_mode": length},
            }

    # ----- intent: channel status -----
    if any(w in msg for w in ["how", "status", "doing", "channel", "stats"]):
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            if not ch:
                return {"response": "I couldn't find your channel.", "action": None}
            subs = ch.yt_subscriber_count or 0
            video_count = ch.yt_video_count or 0
            total_views = ch.yt_view_count or 0
            name = ch.name
        with session_scope() as db:
            vid_count = db.query(Video).filter_by(channel_id=channel_id).count()
            published = db.query(Video).filter_by(channel_id=channel_id, status="published").count()
        return {
            "response": (f"📊 **{name}** status:\n"
                        f"  • YouTube subscribers: {subs:,}\n"
                        f"  • YouTube videos: {video_count:,}\n"
                        f"  • Total views: {total_views:,}\n"
                        f"  • Phoenix-produced videos: {vid_count} ({published} published)"),
            "action": "show_dashboard",
            "action_data": None,
        }

    # ----- intent: what should I make next -----
    if any(w in msg for w in ["next", "should i", "idea", "suggest", "what about"]):
        from .research import run_research
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            niche = ch.niche if ch else "technology"
        report = await run_research(channel_id, niche)
        top = report.topics[:5]
        lines = [f"🎯 Here are 5 trending topics for your niche ({niche}):"]
        for i, t in enumerate(top, 1):
            lines.append(f"  {i}. {t['topic']} (score: {t['score']})")
        lines.append("\nReply with 'make a video about [topic]' to produce one.")
        return {"response": "\n".join(lines), "action": None, "action_data": None}

    # ----- intent: revenue -----
    if any(w in msg for w in ["revenue", "money", "earn", "income", "rpm", "cpm"]):
        from .revenue_tracker import get_revenue_dashboard
        data = get_revenue_dashboard(channel_id)
        return {
            "response": (f"💰 **Revenue dashboard**:\n"
                        f"  • Estimated revenue: ${data.get('total_revenue_usd', 0):.2f}\n"
                        f"  • RPM: ${data.get('rpm_usd', 0):.2f} per 1K views\n"
                        f"  • CPM: ${data.get('cpm_usd', 0):.2f} per 1K impressions\n"
                        f"  • Source: {data.get('source', 'unknown')}"),
            "action": "show_revenue",
            "action_data": None,
        }

    # ----- fallback: general chat via LLM -----
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        channel_name = ch.name if ch else "your channel"
        niche = ch.niche if ch else "technology"
    prompt = [
        {"role": "system", "content": (
            f"You are the AI assistant for a YouTube automation tool called "
            f"Project Phoenix. The user's channel is '{channel_name}' "
            f"(niche: {niche}). Help them with questions about their channel, "
            f"video production, YouTube strategy, and content ideas. Be "
            f"concise and friendly. If they ask to make a video, tell them to "
            f"use the Produce form on the Videos page."
        )},
        {"role": "user", "content": message},
    ]
    text = await llm.chat(prompt, temperature=0.7)
    return {
        "response": text or "I'm not sure how to help with that. Try asking about your channel stats, revenue, or video ideas.",
        "action": None,
        "action_data": None,
    }
