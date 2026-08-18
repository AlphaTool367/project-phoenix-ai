#!/usr/bin/env python3
"""Regression checks for reliability, truthful metrics, and one-command support."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import llm
from test_utils import collect_route_paths


def main() -> int:
    # These assertions are intentionally local and do not call paid providers.
    assert settings.allow_simulated_metrics is False
    assert settings.llm_max_retries >= 0
    assert settings.llm_request_timeout_seconds >= 5
    assert settings.approval_required is False
    assert settings.duration_tolerance_seconds > 0
    assert 0 < settings.duration_tolerance_ratio <= 0.5
    assert "/api/dashboard/health" in collect_route_paths(app.routes)

    response = httpx.Response(429, headers={"Retry-After": "2"})
    assert llm._retry_delay(response, 0) == 2.0

    original_force_mock = settings.force_mock_llm
    settings.force_mock_llm = True
    try:
        result = asyncio.run(llm.chat([{"role": "user", "content": "test"}]))
        assert result is None
    finally:
        settings.force_mock_llm = original_force_mock

    with TestClient(app) as client:
        health = client.get("/api/dashboard/health")
        assert health.status_code == 200
        data = health.json()
        assert data["services"]["analytics"] == "live-only (no invented metrics)"
        settings_view = client.get("/api/settings")
        assert settings_view.status_code == 200
        app_settings = settings_view.json()["app"]
        assert app_settings["allow_simulated_metrics"] is False
        assert "llm_max_retries" in app_settings
        assert app_settings["approval_required"] is False

    print("reliability checks passed: truthful metrics, retry controls, automatic mode, routes, health API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
