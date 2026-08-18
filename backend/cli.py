#!/usr/bin/env python3
"""Project Phoenix AI — command line control center.

Usage:
  python backend/cli.py serve        run API + scheduler (24/7 daemon)
  python backend/cli.py run-once     produce one video now
  python backend/cli.py research     run today's trend research
  python backend/cli.py verify-long  produce + verify a real 10–20 minute video (no upload)
  python backend/cli.py demo         short low-res mock video (safe test)
  python backend/cli.py auth         complete YouTube OAuth consent
  python backend/cli.py status       queue + system summary
  python backend/cli.py import-env   safely merge a non-empty .env file
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# make `app` importable when run as `python backend/cli.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.database import init_db, session_scope  # noqa: E402
from app.models import Channel  # noqa: E402

log = get_logger("cli")


def get_default_channel_id() -> int:
    init_db()
    with session_scope() as db:
        ch = db.query(Channel).first()
        if ch is None:
            from app.main import ensure_default_channel
            ensure_default_channel()
            ch = db.query(Channel).first()
        return ch.id


def cmd_serve(_: argparse.Namespace) -> None:
    import uvicorn

    log.info("starting API on %s:%d", settings.api_host, settings.api_port)
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port,
                reload=False)


def cmd_run_once(args: argparse.Namespace) -> None:
    from app.pipeline.orchestrator import produce_video

    cid = get_default_channel_id()
    video = asyncio.run(produce_video(
        cid, topic=args.topic, publish=not args.no_publish))
    print(f"\nVideo #{video.id}: {video.status} — {video.title or video.topic}")
    print(f"file: {video.file_path}")
    print(f"thumbnail: {video.thumbnail_path}")


def cmd_research(_: argparse.Namespace) -> None:
    from app.services import research

    cid = get_default_channel_id()
    report = asyncio.run(research.run_research(cid, settings.channel_niche))
    print(f"\nTrend report {report.date} (source={report.source})")
    for i, t in enumerate(report.topics[:10], 1):
        print(f"  {i:2d}. [{t['score']:>6}] {t['topic']}  ({t['niche']})")
    print(f"winning niche: {report.winning_niche}")


def cmd_verify_long(args: argparse.Namespace) -> None:
    """Produce a real long-form artifact and verify its final MP4.

    This command never publishes. It is intentionally explicit because a
    10–20 minute render consumes real CPU, disk and provider requests.
    """
    from app.pipeline.orchestrator import produce_video
    from app.services.quality import inspect_rendered_video

    seconds = int(args.seconds)
    cid = get_default_channel_id()
    print(f"Producing a real {seconds // 60}-minute long video (no upload)…")
    video = asyncio.run(produce_video(
        cid,
        topic=args.topic,
        publish=False,
        target_seconds=seconds,
        length_mode="manual",
        clip_shorts=False,
    ))
    report = asyncio.run(inspect_rendered_video(
        video.file_path or "",
        seconds,
        script=video.script_json or {},
    ))
    import json
    print(json.dumps({
        "video_id": video.id,
        "status": video.status,
        "file": video.file_path,
        "requested_seconds": seconds,
        "measured_seconds": report.get("measured_seconds"),
        "quality_score": report.get("quality_score"),
        "passed": report.get("passed"),
        "critical_errors": report.get("critical_errors", []),
        "warnings": report.get("warnings", []),
    }, indent=2))
    if not report.get("passed"):
        raise SystemExit(2)


def cmd_demo(_: argparse.Namespace) -> None:
    """End-to-end smoke test: tiny 3-scene video at 720p, no upload."""
    from app.pipeline.orchestrator import produce_video

    cid = get_default_channel_id()
    print("Producing a short demo video (mock-safe, no upload)…")
    video = asyncio.run(produce_video(
        cid, topic="How AI is quietly running your day",
        publish=False, target_seconds=45))
    print(f"\nDEMO COMPLETE — video #{video.id}: {video.status}")
    print(f"  title:     {video.title}")
    print(f"  file:      {video.file_path}")
    print(f"  thumbnail: {video.thumbnail_path}")
    print(f"  duration:  {video.duration_seconds:.0f}s")


def cmd_auth(_: argparse.Namespace) -> None:
    from app.services.uploader import run_console_auth_flow

    cid = get_default_channel_id()
    ok = run_console_auth_flow(cid)
    print("OAuth complete." if ok else
          "OAuth failed — check GOOGLE_CLIENT_SECRETS_FILE in .env")


def cmd_import_env(args: argparse.Namespace) -> None:
    """Safely merge non-empty values from an external .env file."""
    from app.config import _ENV_FILE_PATH, merge_nonempty_env_file

    try:
        keys, backup = merge_nonempty_env_file(args.file, _ENV_FILE_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ENV IMPORT BLOCKED: {exc}")
        raise SystemExit(2)
    provider_keys = {
        "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY",
        "PEXELS_API_KEY", "PIXABAY_API_KEY", "JAMENDO_CLIENT_ID",
    }
    imported_providers = sorted(provider_keys.intersection(keys))
    print(f"Imported non-empty settings: {len(keys)}")
    print(f"Provider credentials imported: {', '.join(imported_providers) or 'none'}")
    print(f"Backup: {backup or 'none (target did not exist)'}")
    print("Restart Phoenix with ./run.sh to reload the credentials.")


def cmd_status(_: argparse.Namespace) -> None:
    from app.models import Job, Video
    from app.services import health

    init_db()
    with session_scope() as db:
        counts = {}
        for (status,) in db.query(Video.status).distinct():
            counts[status] = db.query(Video).filter_by(status=status).count()
        queued = db.query(Job).filter_by(status="queued").count()
        dead = db.query(Job).filter_by(status="dead").count()
    print("videos:", counts or "none yet")
    print(f"queue: {queued} queued, {dead} dead")
    for k, v in health.api_health()["services"].items():
        print(f"  {k:10s}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="phoenix", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run API + scheduler daemon")

    p = sub.add_parser("run-once", help="produce one video now")
    p.add_argument("--topic", default=None)
    p.add_argument("--no-publish", action="store_true")

    sub.add_parser("research", help="run trend research only")
    p = sub.add_parser("verify-long", help="produce + verify a real 10–20 minute video, never upload")
    p.add_argument("--seconds", type=int, choices=range(600, 1201), metavar="600..1200",
                    default=600, help="target duration in seconds (10–20 minutes)")
    p.add_argument("--topic", default=None)
    sub.add_parser("demo", help="short mock video smoke test")
    sub.add_parser("auth", help="YouTube OAuth consent")
    sub.add_parser("status", help="queue + system summary")
    p = sub.add_parser("import-env", help="safely merge a non-empty .env file")
    p.add_argument("file", help="path to the .env file to merge")

    args = parser.parse_args()
    {
        "serve": cmd_serve, "run-once": cmd_run_once, "research": cmd_research,
        "verify-long": cmd_verify_long, "demo": cmd_demo, "auth": cmd_auth, "status": cmd_status,
        "import-env": cmd_import_env,
    }[args.command](args)


if __name__ == "__main__":
    main()
