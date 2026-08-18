"""Unified LLM client with honest fallbacks and transient-error recovery.

Providers are tried in order: OpenRouter (with optional model fallbacks), Gemini,
and Grok. A missing or unavailable provider returns ``None`` so callers can use
their explicitly labelled template path. This module never claims unlimited
usage: provider quotas, credits, and rate limits remain controlled by the
provider account.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import parse_json_loose
from . import provider_usage

log = get_logger("llm")

_TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 529}
DEFAULT_MAX_TOKENS = 4096


def _max_tokens() -> int:
    """Return a bounded output-token budget."""
    import os

    raw = os.environ.get("OPENROUTER_MAX_TOKENS", "")
    try:
        value = int(raw)
        if 256 <= value <= 32000:
            return value
    except (TypeError, ValueError):
        pass
    return DEFAULT_MAX_TOKENS


def _timeout() -> httpx.Timeout:
    seconds = max(5.0, min(float(settings.llm_request_timeout_seconds), 300.0))
    return httpx.Timeout(seconds, connect=min(15.0, seconds))


def _retry_count() -> int:
    return max(0, min(int(settings.llm_max_retries), 5))


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Use Retry-After when valid, otherwise bounded exponential backoff."""
    if response is not None:
        raw = response.headers.get("Retry-After", "").strip()
        try:
            return max(0.1, min(float(raw), 60.0))
        except ValueError:
            pass
    base = max(0.1, min(float(settings.llm_retry_backoff_seconds), 10.0))
    return min(base * (2 ** attempt), 60.0)


def _short_error(response: httpx.Response) -> str:
    """Return a bounded provider error without exposing credentials."""
    try:
        body = response.json()
        message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        if message:
            return str(message)[:240]
    except (ValueError, TypeError):
        pass
    return response.text[:240].replace("\n", " ")


async def _safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    """Perform a request with async retries for transient failures only."""
    retries = _retry_count()
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
            if response.status_code not in _TRANSIENT_STATUS_CODES or attempt >= retries:
                return response
            delay = _retry_delay(response, attempt)
            log.warning(
                "transient LLM HTTP %s from %s; retry %d/%d in %.1fs",
                response.status_code,
                url.split("/")[2] if "/" in url else "provider",
                attempt + 1,
                retries,
                delay,
            )
            await asyncio.sleep(delay)
        except httpx.TimeoutException as exc:
            last_exc = RuntimeError(f"request timed out: {exc}")
        except httpx.HTTPError as exc:
            last_exc = RuntimeError(f"http error: {exc}")
        if attempt < retries:
            delay = _retry_delay(None, attempt)
            await asyncio.sleep(delay)
    raise last_exc or RuntimeError("LLM request failed without a response")


def _openrouter_models() -> list[str]:
    values = [settings.openrouter_model]
    values.extend(settings.openrouter_fallback_models.split(","))
    seen: set[str] = set()
    models: list[str] = []
    for value in values:
        model = value.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


async def _openrouter(messages: list[dict], temperature: float) -> str:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://github.com/project-phoenix-ai",
        "X-Title": "Project Phoenix AI",
    }
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        for model in _openrouter_models():
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": _max_tokens(),
            }
            response = await _safe_request(
                client,
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json_body=payload,
            )
            if response.status_code >= 400:
                error = f"{model}: HTTP {response.status_code} {_short_error(response)}"
                provider_usage.record_error("openrouter", model, error)
                errors.append(error)
                # A fallback model can recover from model/provider capacity errors.
                if response.status_code in {400, 402, 404, 408, 429, 500, 502, 503, 529}:
                    continue
                raise RuntimeError(error)
            try:
                body = response.json()
                provider_usage.record_response("openrouter", model, body)
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty content")
                return content
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"{model}: malformed response ({exc})")
    raise RuntimeError("OpenRouter models failed: " + " | ".join(errors)[0:900])


async def _gemini(messages: list[dict], temperature: float) -> str:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    prompt = f"{system}\n\n{user}" if system else user
    model = settings.gemini_model or "gemini-2.0-flash"
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        response = await _safe_request(
            client,
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": settings.gemini_api_key},
            json_body={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": _max_tokens(),
                },
            },
        )
        if response.status_code >= 400:
            error = f"Gemini HTTP {response.status_code}: {_short_error(response)}"
            provider_usage.record_error("gemini", model, error)
            raise RuntimeError(error)
        try:
            body = response.json()
            provider_usage.record_response("gemini", model, body)
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned a malformed response") from exc


async def _grok(messages: list[dict], temperature: float) -> str:
    model = settings.grok_model or "grok-2-latest"
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        response = await _safe_request(
            client,
            "POST",
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.grok_api_key}"},
            json_body={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": _max_tokens(),
            },
        )
        if response.status_code >= 400:
            error = f"Grok HTTP {response.status_code}: {_short_error(response)}"
            provider_usage.record_error("grok", model, error)
            raise RuntimeError(error)
        try:
            body = response.json()
            provider_usage.record_response("grok", model, body)
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Grok returned a malformed response") from exc


_PROVIDERS = [
    ("openrouter", lambda: settings.openrouter_api_key, _openrouter),
    ("gemini", lambda: settings.gemini_api_key, _gemini),
    ("grok", lambda: settings.grok_api_key, _grok),
]


async def chat(
    messages: list[dict],
    temperature: float = 0.8,
    prefer_json: bool = False,
) -> str | None:
    """Try configured providers and return ``None`` for explicit template fallback."""
    tried_any = False
    for name, has_key, fn in _PROVIDERS:
        if not has_key() or settings.force_mock_llm:
            continue
        tried_any = True
        try:
            text = await fn(messages, temperature)
            if prefer_json and parse_json_loose(text) is None:
                log.warning("%s returned non-JSON; trying the next provider", name)
                continue
            return text
        except Exception as exc:
            log.warning("LLM provider %s failed: %s", name, exc)
    if not tried_any:
        log.info("no live LLM provider configured — using labelled template engine")
    return None


async def chat_json(messages: list[dict], temperature: float = 0.7) -> Any | None:
    text = await chat(messages, temperature=temperature, prefer_json=True)
    if text is None:
        return None
    data = parse_json_loose(text)
    if data is None:
        log.warning("could not parse JSON from LLM reply (%.120s…)", text)
    return data
