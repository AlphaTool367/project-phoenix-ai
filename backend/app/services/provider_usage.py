"""Truthful provider usage accounting.

This service records only usage metadata returned by providers. It never
calculates a price from guessed rates and never presents a local budget as a
provider balance.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from ..database import session_scope
from ..models import ProviderUsage


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def record_response(
    service: str,
    model: str,
    payload: dict | None,
    *,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Persist provider-reported usage from a response payload."""
    payload = payload or {}
    usage = payload.get("usage") or payload.get("usageMetadata") or {}
    prompt = _int(usage.get("prompt_tokens", usage.get("promptTokenCount")))
    completion = _int(usage.get("completion_tokens", usage.get("candidatesTokenCount")))
    total = _int(usage.get("total_tokens", usage.get("totalTokenCount"))) or prompt + completion
    raw_cost = usage.get("cost", payload.get("cost"))
    try:
        cost = float(raw_cost) if raw_cost is not None else None
    except (TypeError, ValueError):
        cost = None
    cost_source = "provider_response" if cost is not None else "unknown"
    try:
        with session_scope() as db:
            db.add(ProviderUsage(
                service=str(service)[:32], model=str(model)[:160],
                prompt_tokens=prompt, completion_tokens=completion,
                total_tokens=total, reported_cost_usd=cost,
                cost_source=cost_source, status=str(status)[:16],
                error=str(error)[:1000] if error else None,
            ))
    except Exception:
        # Usage telemetry must never break video generation.
        return


def record_error(service: str, model: str, error: str) -> None:
    record_response(service, model, {}, status="error", error=error)


def summary(days: int = 1) -> dict:
    """Return daily/period totals; unknown costs remain explicit."""
    days = max(1, min(int(days), 90))
    since = datetime.utcnow() - timedelta(days=days)
    with session_scope() as db:
        rows = (db.query(ProviderUsage)
                .filter(ProviderUsage.created_at >= since)
                .order_by(ProviderUsage.created_at.desc()).all())
    by_service: dict[str, dict] = {}
    for row in rows:
        item = by_service.setdefault(row.service, {
            "service": row.service, "requests": 0, "successful_requests": 0,
            "failed_requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_tokens": 0, "reported_cost_usd": 0.0,
            "cost_records": 0, "cost_status": "unknown",
            "models": {},
        })
        item["requests"] += int(row.request_count or 1)
        item["successful_requests"] += 1 if row.status == "success" else 0
        item["failed_requests"] += 1 if row.status != "success" else 0
        item["prompt_tokens"] += int(row.prompt_tokens or 0)
        item["completion_tokens"] += int(row.completion_tokens or 0)
        item["total_tokens"] += int(row.total_tokens or 0)
        if row.reported_cost_usd is not None:
            item["reported_cost_usd"] += float(row.reported_cost_usd)
            item["cost_records"] += 1
        item["models"][row.model] = item["models"].get(row.model, 0) + 1
    for item in by_service.values():
        item["cost_status"] = (
            "provider_reported" if item["cost_records"] else "unknown_provider_cost"
        )
        if not item["cost_records"]:
            item["reported_cost_usd"] = None
    return {
        "period_days": days,
        "since_utc": since.isoformat(),
        "services": list(by_service.values()),
        "provider_balances": {
            "openrouter": "unknown — check provider account/API endpoint",
            "gemini": "unknown — check Google AI Studio/Cloud billing",
            "grok": "unknown — check xAI console",
        },
        "note": "Token/cost values are provider-response data only; no estimated prices or fake balances are shown.",
    }
