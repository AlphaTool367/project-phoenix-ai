"""Production Safety Pack services.

This module keeps safety actions explicit and auditable. Backups intentionally
exclude `.env`, OAuth tokens, and other secrets. Quota values are local
accounting only; provider-side balances remain authoritative and are reported
as unknown unless an official provider endpoint is queried.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import ActivityLog, NotificationLog

log = get_logger("safety")


def _backup_dir() -> Path:
    path = settings.path(settings.data_dir, "backups")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        return Path(raw) if Path(raw).is_absolute() else settings.path(raw)
    raise RuntimeError("Safety backup currently supports SQLite only")


def _log_activity(level: str, source: str, message: str, context: dict | None = None) -> None:
    with session_scope() as db:
        db.add(ActivityLog(level=level, source=source, message=message, context=context or {}))


def record_notification(
    channel_id: int,
    notification_type: str,
    subject: str,
    body: str,
    *,
    delivered: bool = False,
) -> dict[str, Any]:
    """Persist an alert even when no external delivery connector is configured."""
    with session_scope() as db:
        row = NotificationLog(
            channel_id=channel_id,
            notification_type=notification_type,
            subject=subject[:300],
            body=body,
            delivered=delivered,
        )
        db.add(row)
        db.flush()
        result = {
            "id": row.id,
            "channel_id": channel_id,
            "type": notification_type,
            "subject": row.subject,
            "delivered": delivered,
            "sent_at": row.sent_at.isoformat(),
        }
    _log_activity("INFO" if delivered else "WARNING", "notifications", subject[:200], result)
    return result


def list_notifications(channel_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as db:
        query = db.query(NotificationLog).order_by(NotificationLog.id.desc())
        if channel_id is not None:
            query = query.filter(NotificationLog.channel_id == channel_id)
        rows = query.limit(max(1, min(limit, 500))).all()
        return [
            {
                "id": row.id,
                "channel_id": row.channel_id,
                "type": row.notification_type,
                "subject": row.subject,
                "body": row.body,
                "delivered": row.delivered,
                "sent_at": row.sent_at.isoformat(),
            }
            for row in rows
        ]


def create_backup() -> dict[str, Any]:
    """Create a safe, timestamped ZIP backup without secrets."""
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = _backup_dir() / f"phoenix-backup-{stamp}.zip"
    db_path = _db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    temp_db = _backup_dir() / f".{stamp}.db.tmp"
    try:
        source = sqlite3.connect(str(db_path))
        target = sqlite3.connect(str(temp_db))
        with target:
            source.backup(target)
        target.close()
        source.close()
        manifest = {
            "created_at": datetime.utcnow().isoformat(),
            "format": 1,
            "database": "phoenix.db",
            "secrets_excluded": True,
            "note": "OAuth tokens and .env are intentionally excluded.",
        }
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(temp_db, "phoenix.db")
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            example = settings.path(".env.example")
            if example.exists():
                archive.write(example, ".env.example")
    finally:
        temp_db.unlink(missing_ok=True)

    prune_backups()
    result = {
        "name": out.name,
        "path": str(out),
        "size_bytes": out.stat().st_size,
        "created_at": datetime.utcnow().isoformat(),
        "secrets_excluded": True,
    }
    _log_activity("INFO", "backup", f"Backup created: {out.name}", result)
    return result


def list_backups() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(_backup_dir().glob("phoenix-backup-*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            rows.append({
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat(),
                "valid": "phoenix.db" in names and "manifest.json" in names,
                "secrets_excluded": ".env" not in names and "tokens" not in " ".join(names),
            })
        except (OSError, zipfile.BadZipFile):
            rows.append({"name": path.name, "size_bytes": 0, "valid": False})
    return rows


def prune_backups() -> int:
    cutoff = datetime.utcnow() - timedelta(days=max(1, settings.backup_retention_days))
    removed = 0
    for path in _backup_dir().glob("phoenix-backup-*.zip"):
        if datetime.utcfromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def restore_backup(name: str) -> dict[str, Any]:
    """Restore database only; caller must enforce explicit confirmation."""
    if Path(name).name != name or not name.endswith(".zip"):
        raise ValueError("invalid backup name")
    source_zip = _backup_dir() / name
    if not source_zip.exists():
        raise FileNotFoundError("backup not found")
    with zipfile.ZipFile(source_zip) as archive:
        names = set(archive.namelist())
        if "phoenix.db" not in names or "manifest.json" not in names:
            raise ValueError("backup manifest or database is missing")
        manifest = json.loads(archive.read("manifest.json"))
        if not manifest.get("secrets_excluded"):
            raise ValueError("refusing backup without secret-exclusion marker")
        temp = settings.path(settings.data_dir, ".restore-phoenix.db.tmp")
        with archive.open("phoenix.db") as src, temp.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    target = _db_path()
    old = target.with_suffix(target.suffix + ".before-restore")
    shutil.copy2(target, old)
    shutil.move(temp, target)
    _log_activity("WARNING", "backup", f"Database restored from {name}", {"previous_copy": str(old)})
    return {"restored": True, "name": name, "previous_copy": str(old)}


def quota_status() -> dict[str, Any]:
    """Return honest local accounting and unknown provider-side balance."""
    today = datetime.utcnow().date().isoformat()
    # Current implementation uses ActivityLog for local events; no fake remote
    # balance is invented. The dashboard can still show configured budget.
    with session_scope() as db:
        events = db.query(ActivityLog).filter(
            ActivityLog.source.in_(["youtube-quota", "openrouter-quota"]),
            ActivityLog.ts >= datetime.combine(datetime.utcnow().date(), datetime.min.time()),
        ).all()
    used = 0
    by_service: dict[str, int] = {}
    for event in events:
        units = int((event.context or {}).get("units", 0) or 0)
        service = str((event.context or {}).get("service", "unknown"))
        used += units
        by_service[service] = by_service.get(service, 0) + units
    return {
        "date_utc": today,
        "youtube": {
            "configured_daily_budget_units": settings.youtube_daily_quota_units,
            "locally_tracked_units": by_service.get("youtube", 0),
            "remaining_local_budget_units": max(0, settings.youtube_daily_quota_units - by_service.get("youtube", 0)),
            "provider_balance": "unknown — YouTube does not expose a simple remaining-quota endpoint",
        },
        "openrouter": {
            "locally_tracked_units": by_service.get("openrouter", 0),
            "provider_balance": "check OpenRouter account/API key endpoint",
        },
        "total_local_units": used,
    }


def record_quota_event(service: str, units: int, message: str, *, channel_id: int | None = None) -> None:
    _log_activity("INFO", f"{service}-quota", message, {
        "service": service,
        "units": max(0, int(units)),
        "channel_id": channel_id,
    })


async def deliver_webhook(payload: dict[str, Any]) -> bool:
    """Optionally deliver a notification; disabled unless a URL is configured."""
    import os

    url = os.environ.get("NOTIFICATION_WEBHOOK_URL", "").strip()
    if not settings.notifications_enabled or not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True
    except Exception as exc:
        log.warning("notification webhook failed: %s", exc)
        return False
