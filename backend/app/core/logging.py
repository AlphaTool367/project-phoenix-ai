"""Logging: console + rotating file + DB activity log + websocket broadcast."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from ..config import settings

_ws_subscribers: set[asyncio.Queue] = set()
_db_writer_available = True  # flipped off while DB is initializing


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _ws_subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _ws_subscribers.discard(q)


def _broadcast(payload: dict[str, Any]) -> None:
    for q in list(_ws_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class DBActivityHandler(logging.Handler):
    """Mirror log records into the activity_logs table + websocket."""

    def emit(self, record: logging.LogRecord) -> None:
        if not _db_writer_available:
            return
        try:
            from ..database import session_scope
            from ..models import ActivityLog

            entry = {
                "ts": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "source": record.name.split(".")[-1],
                "message": record.getMessage(),
            }
            with session_scope() as db:
                db.add(ActivityLog(
                    level=record.levelname,
                    source=entry["source"],
                    message=entry["message"],
                ))
            _broadcast(entry)
        except Exception:
            pass  # logging must never crash the app


def setup_logging() -> logging.Logger:
    log_dir = settings.path(settings.data_dir, "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("phoenix")
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    if root.handlers:  # idempotent
        return root

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    fileh = RotatingFileHandler(log_dir / "phoenix.log", maxBytes=5_000_000, backupCount=5)
    fileh.setFormatter(fmt)
    root.addHandler(fileh)

    root.addHandler(DBActivityHandler())
    return root


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"phoenix.{name}")
