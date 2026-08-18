#!/usr/bin/env python3
"""Production Safety Pack integration checks."""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import engine, session_scope
from app.main import app
from app.models import Video


def main() -> int:
    with TestClient(app) as client:
        for path in (
            "/api/safety/summary",
            "/api/safety/review-queue",
            "/api/safety/calendar?days=7",
            "/api/safety/errors",
            "/api/safety/backups",
            "/api/safety/notifications",
            "/api/safety/quota",
        ):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code, response.text[:200])
        print("✓ safety read endpoints")

        columns = {c["name"] for c in inspect(engine).get_columns("videos")}
        for name in ("review_status", "review_notes", "reviewed_at", "reviewed_by"):
            assert name in columns, name
        print("✓ existing database migration columns")

        with session_scope() as db:
            channel_id = db.query(Video.channel_id).first()[0]
            temp = Video(
                channel_id=channel_id,
                topic="Safety test temporary video",
                title="Safety test temporary video",
                status="rendered",
                review_status="pending",
                file_path=str(Path(tempfile.gettempdir()) / "phoenix-safety-test.mp4"),
            )
            Path(temp.file_path).write_bytes(b"test")
            db.add(temp)
            db.flush()
            video_id = temp.id
        try:
            rejected = client.post(f"/api/safety/review/{video_id}", json={
                "action": "reject", "notes": "test rejection", "reviewer": "test-suite"
            })
            assert rejected.status_code == 202, rejected.text
            with session_scope() as db:
                row = db.get(Video, video_id)
                assert row.review_status == "rejected"
                assert row.status == "rejected"
            print("✓ review reject transition and audit path")
        finally:
            with session_scope() as db:
                row = db.get(Video, video_id)
                if row:
                    db.delete(row)
            Path(tempfile.gettempdir(), "phoenix-safety-test.mp4").unlink(missing_ok=True)

        backup = client.post("/api/safety/backups")
        assert backup.status_code == 201, backup.text
        backup_data = backup.json()
        with zipfile.ZipFile(backup_data["path"]) as archive:
            names = archive.namelist()
            assert "phoenix.db" in names and "manifest.json" in names
            assert ".env" not in names
            assert not any("token" in name.lower() for name in names)
        print("✓ safe backup creation and secret exclusion")

        restore_without_confirm = client.post(
            f"/api/safety/backups/{backup_data['name']}/restore", json={"confirm": False}
        )
        assert restore_without_confirm.status_code == 400
        print("✓ restore confirmation guard")

        quota = client.get("/api/safety/quota").json()
        assert quota["youtube"]["provider_balance"].startswith("unknown")
        print("✓ quota monitor does not invent provider balance")

    print("ALL SAFETY PACK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
