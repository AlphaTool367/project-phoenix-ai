"""Shared helpers: retries, subprocess, text, timing.

Cross-platform safe subprocess execution (Windows / Linux / macOS).
Resolves ffmpeg / ffprobe to absolute paths before spawning so we never
hit FileNotFoundError ([WinError 2]) when the tool is on PATH but the
asyncio child-spawner can't resolve it.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import shutil
import sys
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


# ----------------------------------------------------------------- text utils
def slugify(text: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:maxlen] or "video"


def clamp(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def parse_json_loose(text: str) -> Any:
    """Extract the first JSON object/array from an LLM reply."""
    text = (text or "").strip()
    for pattern in (r"```(?:json)?\s*(.*?)```", r"(\{.*\}|\[.*\])"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ----------------------------------------------------------------- retry deco
def retry(times: int = 3, base_delay: float = 2.0, exceptions=(Exception,)):
    """Exponential-backoff retry decorator for async functions."""

    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last: Exception | None = None
            for attempt in range(1, times + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last = exc
                    if attempt < times:
                        await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
            raise last  # type: ignore[misc]

        return wrapper

    return deco


# ----------------------------------------------------- ffmpeg / ffprobe paths
_FFMPEG_PATH: str | None = None
_FFPROBE_PATH: str | None = None


def _resolve_bin(name: str) -> str | None:
    """Resolve a binary to an absolute path; on Windows also try .exe."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform.startswith("win"):
        for ext in (".exe", ".bat", ".cmd"):
            found = shutil.which(name + ext)
            if found:
                return found
    return None


def ffmpeg_bin() -> str:
    """Absolute path to ffmpeg (raises RuntimeError if missing)."""
    global _FFMPEG_PATH
    if _FFMPEG_PATH is None:
        _FFMPEG_PATH = _resolve_bin("ffmpeg")
    if _FFMPEG_PATH is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg "
            "(https://ffmpeg.org/download.html) and ensure it is on PATH, "
            "or set FFMPEG_PATH env var to its absolute location."
        )
    return _FFMPEG_PATH


def ffprobe_bin() -> str:
    """Absolute path to ffprobe (raises RuntimeError if missing)."""
    global _FFPROBE_PATH
    if _FFPROBE_PATH is None:
        _FFPROBE_PATH = _resolve_bin("ffprobe")
    if _FFPROBE_PATH is None:
        raise RuntimeError(
            "ffprobe not found on PATH. Install ffmpeg "
            "(https://ffmpeg.org/download.html) and ensure it is on PATH."
        )
    return _FFPROBE_PATH


def ffmpeg_available() -> bool:
    try:
        ffmpeg_bin()
        ffprobe_bin()
        return True
    except RuntimeError:
        return False


# Allow user to override via env (e.g. FFMPEG_PATH=/usr/local/bin/ffmpeg)
if os.environ.get("FFMPEG_PATH"):
    _FFMPEG_PATH = os.environ["FFMPEG_PATH"]
if os.environ.get("FFPROBE_PATH"):
    _FFPROBE_PATH = os.environ["FFPROBE_PATH"]


# --------------------------------------------------------- subprocess runner
async def run_cmd(cmd: list[str], timeout: int = 1800) -> tuple[int, str, str]:
    """Run a subprocess command asynchronously, return (rc, stdout, stderr).

    Cross-platform safe:
      - Resolves the executable to an absolute path (Windows-safe).
      - Uses create_subprocess_exec (no shell) on POSIX.
      - On Windows Python 3.8+ uses Proactor event loop by default which
        supports subprocess; this is just defensive.
    """
    if not cmd:
        raise ValueError("empty command")

    # Resolve the executable (cmd[0]) to an absolute path when possible.
    exe = cmd[0]
    if not os.path.isabs(exe):
        resolved = _resolve_bin(exe) or shutil.which(exe)
        if resolved:
            cmd = [resolved, *cmd[1:]]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"executable not found while running: {exe}. "
            f"Original error: {exc}"
        ) from exc

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise RuntimeError(f"command timed out: {' '.join(cmd[:3])}…")
    return (
        proc.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


async def probe_duration(path: str) -> float:
    """Get media duration in seconds via ffprobe (0.0 on failure)."""
    try:
        rc, out, _ = await run_cmd([
            ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ])
    except RuntimeError:
        return 0.0
    if rc != 0:
        return 0.0
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "•" * max(4, len(key) - 8) + key[-4:] if len(key) > 8 else "••••"
