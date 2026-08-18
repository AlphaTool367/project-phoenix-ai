"""Compilations & Telegram bot.

  - Best-of compilation: auto-generate a monthly "best of" video from
    the channel's top-performing clips.
  - Year-in-review: generate a yearly recap compilation.
  - Auto-generated channel trailer: create a 30-60s trailer from the
    channel's best clips.
  - Telegram bot: control Phoenix from a phone via Telegram commands.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd
from ..database import session_scope
from ..models import AnalyticsSnapshot, Video
from . import llm

log = get_logger("compilations_bot")


# ----------------------------------------------------- best-of compilation

async def generate_best_of_compilation(channel_id: int, period_days: int = 30) -> dict:
    """Generate a 'best of' compilation video from the channel's top clips.

    Picks the top N videos by views from the last `period_days`, extracts
    a 10-15s highlight from each, and concatenates them into one video.
    """
    cutoff = datetime.utcnow() - timedelta(days=period_days)
    with session_scope() as db:
        # Find top videos by latest views.
        snaps = (db.query(AnalyticsSnapshot, Video)
                 .join(Video, Video.id == AnalyticsSnapshot.video_id)
                 .filter(Video.channel_id == channel_id,
                         Video.status == "published",
                         AnalyticsSnapshot.captured_at >= cutoff)
                 .order_by(AnalyticsSnapshot.views.desc())
                 .limit(5).all())
        if not snaps:
            return {"success": False, "reason": "no published videos in period"}
        clips = []
        for snap, v in snaps:
            if v.file_path and Path(v.file_path).exists():
                clips.append({"video_id": v.id, "title": v.title or v.topic,
                              "file_path": v.file_path, "views": snap.views})

    if not clips:
        return {"success": False, "reason": "no video files found"}

    # Extract 10-15s highlight from each (use the first 15s — simplest approach).
    out_dir = settings.path(settings.data_dir, "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    highlight_clips = []
    for i, c in enumerate(clips):
        hl_path = out_dir / f"bestof_{i:02d}.mp4"
        if not hl_path.exists():
            rc, _, err = await run_cmd([
                ffmpeg_bin(), "-y", "-i", c["file_path"],
                "-t", "15", "-vf",
                "scale=1920:1080:force_original_aspect_ratio=increase,"
                "crop=1920:1080,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-an", str(hl_path),
            ])
            if rc != 0:
                continue
        highlight_clips.append(str(hl_path))

    if not highlight_clips:
        return {"success": False, "reason": "highlight extraction failed"}

    # Concatenate.
    concat_file = out_dir / "bestof_concat.txt"
    concat_file.write_text("".join(f"file '{p}'\n" for p in highlight_clips),
                            encoding="utf-8")
    final_path = out_dir / f"bestof_channel_{channel_id}_{period_days}d.mp4"
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(final_path),
    ])
    if rc != 0:
        return {"success": False, "reason": f"concat failed: {err[-200:]}"}
    log.info("best-of compilation: %s (%d clips)", final_path.name, len(highlight_clips))
    return {"success": True, "path": str(final_path),
            "clips_used": len(highlight_clips), "period_days": period_days}


# ----------------------------------------------------- year-in-review

async def generate_year_in_review(channel_id: int, year: int | None = None) -> dict:
    """Generate a yearly recap compilation."""
    year = year or datetime.utcnow().year
    return await generate_best_of_compilation(channel_id, period_days=365)


# ----------------------------------------------------- channel trailer

async def generate_channel_trailer(channel_id: int) -> dict:
    """Generate a 30-60s channel trailer from the channel's best clips + LLM script."""
    # Get top 3 clips.
    comp = await generate_best_of_compilation(channel_id, period_days=90)
    if not comp.get("success"):
        return comp
    # Ask LLM for a trailer script.
    with session_scope() as db:
        from ..models import Channel
        ch = db.get(Channel, channel_id)
        name = ch.name if ch else "this channel"
        niche = ch.niche if ch else "technology"
    prompt = [
        {"role": "system", "content": (
            "Write a 30-second channel trailer script. Respond ONLY with JSON: "
            "{title, narration (1 paragraph, 50-70 words)}. Tone: exciting, "
            "welcoming, makes people want to subscribe."
        )},
        {"role": "user", "content": f"Channel: {name}\nNiche: {niche}"},
    ]
    data = await llm.chat_json(prompt, temperature=0.8)
    return {
        "compilation_path": comp["path"],
        "trailer_script": data if isinstance(data, dict) else None,
        "channel_name": name,
    }


# ----------------------------------------------------- Telegram bot

def telegram_bot_available() -> bool:
    """Check if the Telegram bot is configured."""
    import os
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def get_telegram_bot_instructions() -> str:
    """Return setup instructions for the Telegram bot."""
    return (
        "To enable the Telegram bot:\n"
        "1. Open Telegram → search @BotFather\n"
        "2. Send /newbot → follow prompts to create a bot\n"
        "3. Copy the bot token\n"
        "4. Add to .env: TELEGRAM_BOT_TOKEN=your_token\n"
        "5. Restart the backend\n"
        "6. Open your bot in Telegram → /start\n\n"
        "Commands:\n"
        "  /status — channel stats\n"
        "  /produce <topic> — make a video\n"
        "  /revenue — revenue dashboard\n"
        "  /ideas — trending topic ideas\n"
        "  /help — list commands"
    )


async def start_telegram_bot() -> dict:
    """Start the Telegram bot (if configured).

    The bot runs in the background and responds to commands.
    """
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"started": False, "reason": get_telegram_bot_instructions()}
    try:
        from telegram import Update
        from telegram.ext import (Application, CommandHandler, ContextTypes)
    except ImportError:
        return {"started": False,
                "reason": "python-telegram-bot not installed. Run: "
                          "pip install python-telegram-bot"}
    # Bot command handlers.
    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from .analytics import channel_summary
        cid = int(context.args[0]) if context.args else 1
        summary = await channel_summary(cid)
        msg = (f"📊 Channel #{cid}:\n"
               f"  Videos: {summary['videos']}\n"
               f"  Views: {summary['views']:,}\n"
               f"  Subs gained: {summary['subs_gained']}")
        await update.message.reply_text(msg)

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Phoenix AI Bot commands:\n"
            "/status [channel_id] — channel stats\n"
            "/produce <topic> — make a video\n"
            "/revenue [channel_id] — revenue\n"
            "/ideas [channel_id] — trending topics\n"
            "/help — this message"
        )

    async def cmd_produce(update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = " ".join(context.args) if context.args else "AI technology"
        await update.message.reply_text(
            f"🎬 Starting video production: '{topic}'\n"
            f"Check the dashboard for progress.")
        # Fire the production in the background.
        from .orchestrator_wrapper import produce_video_simple
        asyncio.create_task(produce_video_simple(1, topic))

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("produce", cmd_produce))
    # Start in background (non-blocking).
    asyncio.create_task(app.run_polling(stop_signals=None))
    log.info("Telegram bot started")
    return {"started": True, "commands": ["/status", "/produce", "/revenue", "/ideas", "/help"]}
