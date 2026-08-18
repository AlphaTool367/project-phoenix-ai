"""Smart automation — dead video auto-private, COPPA checker, sponsor disclosure,
email alerts, milestone videos.

These features run automatically (scheduler) or on-demand:
  - Dead video auto-private: videos with <50% channel average views after
    14 days are set to private (protects channel average).
  - COPPA compliance check: LLM scores whether the video is "made for kids".
  - Sponsor disclosure auto-insert: adds "#ad" / "sponsored" to description
    when a sponsor segment is detected.
  - Email alerts: sends email on milestones (1K, 10K subs) or anomalies.
  - Milestone videos: generates a special video script at subscriber milestones.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from ..database import session_scope
from ..models import Channel, Video

log = get_logger("smart_automation")


# ----------------------------------------------------- dead video auto-private

def find_dead_videos(channel_id: int, days: int = 14,
                     threshold_pct: float = 0.5) -> list[dict]:
    """Find published videos that underperformed after `days` and should be
    auto-privated to protect the channel's average."""
    from ..models import AnalyticsSnapshot
    cutoff = datetime.utcnow() - timedelta(days=days)
    with session_scope() as db:
        videos = (db.query(Video)
                  .filter(Video.channel_id == channel_id,
                          Video.status == "published",
                          Video.published_at < cutoff).all())
        if not videos:
            return []
        vid_views = []
        for v in videos:
            snap = (db.query(AnalyticsSnapshot)
                    .filter(AnalyticsSnapshot.video_id == v.id)
                    .order_by(AnalyticsSnapshot.captured_at.desc())
                    .first())
            views = snap.views if snap else 0
            vid_views.append((v, views))
        avg = sum(w for _, w in vid_views) / len(vid_views) if vid_views else 0
        dead = [(v, w) for v, w in vid_views if w < avg * threshold_pct and avg > 0]
        return [{"video_id": v.id, "title": v.title or v.topic,
                 "views": w, "channel_avg": int(avg),
                 "yt_video_id": v.yt_video_id}
                for v, w in dead]


def auto_private_dead_videos(channel_id: int) -> dict:
    """Set dead videos to private via the YouTube API."""
    from .uploader import set_video_privacy
    dead = find_dead_videos(channel_id)
    privated = 0
    for d in dead:
        if d.get("yt_video_id") and not d["yt_video_id"].startswith("DRYRUN"):
            ok = set_video_privacy(channel_id, d["yt_video_id"], "private")
            if ok:
                with session_scope() as db:
                    v = db.get(Video, d["video_id"])
                    if v:
                        v.status = "archived"  # new status for auto-privated
                privated += 1
                log.info("auto-privated dead video %s (views=%d, avg=%d)",
                         d["yt_video_id"], d["views"], d["channel_avg"])
    return {"checked": len(dead), "privated": privated}


# ----------------------------------------------------- COPPA compliance

async def check_coppa(video_id: int) -> dict:
    """Check if a video is likely to be flagged as 'made for kids' (COPPA)."""
    from . import llm
    with session_scope() as db:
        v = db.get(Video, video_id)
        if not v:
            return {"available": False, "reason": "video not found"}
        title = v.title or v.topic
        niche = v.niche
        description = (v.description or "")[:500]
    prompt = [
        {"role": "system", "content": (
            "You are a COPPA compliance expert. Determine if this YouTube video "
            "would be classified as 'made for kids' under COPPA. Consider: "
            "target audience, subject matter, language, visuals. Respond ONLY "
            "with JSON: {made_for_kids: bool, confidence: 0-100, reasons: [str], "
            "recommendation: str}."
        )},
        {"role": "user", "content": f"Title: {title}\nNiche: {niche}\nDescription: {description}"},
    ]
    data = await llm.chat_json(prompt, temperature=0.3)
    if isinstance(data, dict):
        return data
    return {"made_for_kids": False, "confidence": 50,
            "reasons": ["unable to determine — manual review recommended"],
            "recommendation": "review manually"}


# ----------------------------------------------------- sponsor disclosure

def add_sponsor_disclosure(description: str, sponsor_name: str = "") -> str:
    """Add a sponsor disclosure to a video description.

    YouTube requires sponsored content to be disclosed. This adds a
    clear disclosure at the top of the description.
    """
    if not sponsor_name:
        return description
    disclosure = (f"⚠️ This video is sponsored by {sponsor_name}. "
                  f"Some links may be affiliate links.\n\n")
    return disclosure + description


# ----------------------------------------------------- email alerts

def send_email_alert(subject: str, body: str, to_email: str = "") -> bool:
    """Send an email alert (milestones, anomalies, etc.).

    Uses SMTP. Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env.
    Returns True on success, False on failure.
    """
    import os
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    to = to_email or os.environ.get("ALERT_EMAIL", user)
    if not host or not user or not password:
        log.debug("SMTP not configured — skipping email alert")
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[Phoenix AI] {subject}"
        msg["From"] = user
        msg["To"] = to
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        log.info("email alert sent: %s", subject)
        return True
    except Exception as exc:
        log.warning("email alert failed: %s", exc)
        return False


def check_milestones(channel_id: int) -> dict:
    """Check if the channel hit a subscriber milestone and trigger alerts."""
    MILESTONES = [100, 1000, 5000, 10000, 50000, 100000, 500000, 1_000_000]
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        if not ch or ch.yt_subscriber_count is None:
            return {"checked": False, "reason": "no subscriber data"}
        subs = ch.yt_subscriber_count
        name = ch.name
    for m in MILESTONES:
        if subs >= m and subs < m * 1.01:  # within 1% of milestone
            subject = f"🎉 {name} hit {m:,} subscribers!"
            body = (f"Congratulations! Your channel '{name}' just reached "
                    f"{m:,} subscribers. Keep up the great work!\n\n"
                    f"Current stats:\n  Subscribers: {subs:,}\n")
            send_email_alert(subject, body)
            return {"checked": True, "milestone": m, "alerted": True}
    return {"checked": True, "milestone": None, "alerted": False}


# ----------------------------------------------------- milestone video script

async def generate_milestone_script(channel_id: int, milestone: int) -> dict:
    """Generate a special 'thank you' video script for a subscriber milestone."""
    from . import llm
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        name = ch.name if ch else "the channel"
        niche = ch.niche if ch else "technology"
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube scriptwriter. Write a heartfelt 'thank you' "
            "video script for hitting a subscriber milestone. Respond ONLY "
            "with JSON: {title_options: [3 strings], scenes: [{index, beat, "
            "narration, visual_query, emphasis}]}. 4 scenes max. Tone: "
            "grateful, personal, excited."
        )},
        {"role": "user", "content": (
            f"Channel: {name}\nNiche: {niche}\nMilestone: {milestone:,} subscribers\n"
            f"Write a thank you script."
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.8)
    return data or {}
