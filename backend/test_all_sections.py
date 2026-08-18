#!/usr/bin/env python3
"""Smoke-test every dashboard section and the core feature endpoints."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from app.main import app

PAGES = ["/", "/videos", "/cartoons", "/ai-story", "/remix", "/channels",
         "/analytics", "/monitor", "/scheduler", "/logs", "/safety", "/settings"]

with TestClient(app) as client:
    for page in PAGES:
        response = client.get(page)
        assert response.status_code == 200, (page, response.status_code, response.text[:200])
        assert "Project Phoenix" in response.text, page
        print("PAGE 200", page)

    checks = [
        ("GET", "/api/channels", None),
        ("GET", "/api/settings", None),
        ("GET", "/api/dashboard/summary", None),
        ("GET", "/api/analytics/summary", None),
        ("GET", "/api/v21/cartoon/ytdlp-available", None),
        ("GET", "/api/v21/story/genres", None),
        ("GET", "/api/safety/summary", None),
        ("GET", "/api/safety/calendar?days=7", None),
        ("GET", "/api/safety/errors", None),
        ("GET", "/api/safety/quota", None),
        ("POST", "/api/v21/cartoon/search", {"query": "test cartoon", "max_results": 1}),
    ]
    for method, path, body in checks:
        response = client.request(method, path, json=body)
        assert response.status_code == 200, (method, path, response.status_code, response.text[:300])
        print("API 200", method, path)

    # Remix must either create a real output or report a clear dependency/audio error;
    # it must never return a fake success with no MP4 path.
    remix = client.post("/api/v21/remix/create", json={
        "source_path": "data/output/v8_final.mp4", "language": "en",
        "auto_upload": False, "channel_id": 1,
    })
    assert remix.status_code == 200, remix.text
    remix_data = remix.json()
    if remix_data.get("success"):
        assert remix_data.get("path") and Path(remix_data["path"]).exists()
        print("REMIX real output", remix_data.get("transcript_method"))
    else:
        assert remix_data.get("next_step") or remix_data.get("reason")
        print("REMIX actionable error", remix_data.get("reason"))

print("ALL SECTION SMOKE TESTS PASSED")
