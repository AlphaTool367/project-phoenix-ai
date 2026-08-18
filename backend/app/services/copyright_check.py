"""Pre-upload copyright check via AcoustID + Chromaprint.

Before uploading a rendered video, this module fingerprints the audio track
and looks it up against AcoustID's database of 200+ million tracks. If a
match with a high score is found, the video is flagged so the user can
swap the music or mute the offending section.

AcoustID is free (3 req/sec, unlimited daily). The Chromaprint tool
(`fpcalc`) is required to compute the fingerprint from a WAV/MP3 file.
When fpcalc is missing, the check is skipped with a clear log message.

Flow:
  1. Extract the audio track from the rendered video (ffmpeg).
  2. Compute the Chromaprint fingerprint (`fpcalc -json`).
  3. Submit to AcoustID's `/lookup` endpoint.
  4. If a match with score >= settings.copyright_score_threshold is found,
     return a flagged result with the matched recording(s).
  5. Otherwise return a "clean" result.

The orchestrator uses this BEFORE calling upload_video so the user gets a
chance to swap the music without burning an upload quota slot.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd

log = get_logger("copyright_check")

ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"


def _fpcalc_path() -> str | None:
    """Resolve the fpcalc binary (Chromaprint).

    Checks in this order:
      1. settings.fpcalc_path (explicit path in .env)
      2. FPCALC_PATH environment variable
      3. shutil.which("fpcalc") (system PATH)
      4. On Windows: try fpcalc.exe in the project's secrets/ folder
    """
    # 1. Explicit setting
    if settings.fpcalc_path:
        p = Path(settings.fpcalc_path)
        if p.exists():
            return str(p)
    # 2. Env var
    env_path = os.environ.get("FPCALC_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return str(p)
    # 3. System PATH
    found = shutil.which("fpcalc")
    if found:
        return found
    # 4. Windows: try fpcalc.exe in secrets/ folder
    if sys.platform.startswith("win"):
        from ..config import ROOT_DIR
        for candidate in (ROOT_DIR / "secrets" / "fpcalc.exe",
                          ROOT_DIR / "fpcalc.exe",
                          ROOT_DIR / "chromaprint" / "fpcalc.exe"):
            if candidate.exists():
                return str(candidate)
    return None


def fpcalc_available() -> bool:
    return _fpcalc_path() is not None


async def extract_audio(video_path: str | Path, out_wav: Path) -> bool:
    """Extract the audio track of a rendered video to a 16-bit mono WAV
    (Chromaprint's preferred format). Returns True on success."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if out_wav.exists() and out_wav.stat().st_size > 1000:
        return True
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "44100", "-sample_fmt", "s16",
        str(out_wav),
    ])
    if rc != 0:
        log.warning("audio extract failed for %s: %s", video_path, err[-200:])
        return False
    return True


async def compute_fingerprint(wav_path: Path) -> dict | None:
    """Compute the Chromaprint fingerprint + duration via fpcalc.

    Returns {duration, fingerprint} on success, None on failure.
    """
    fpcalc = _fpcalc_path()
    if fpcalc is None:
        log.warning("fpcalc not installed — skipping fingerprint step. "
                    "Install chromaprint-tools on your system.")
        return None
    rc, out, err = await run_cmd([
        fpcalc, "-json", "-length", "120", str(wav_path),
    ])
    if rc != 0:
        log.warning("fpcalc failed: %s", err[-200:])
        return None
    try:
        data = json.loads(out)
        return {
            "duration": float(data.get("duration", 0)),
            "fingerprint": str(data.get("fingerprint", "")),
        }
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("fpcalc output parse failed: %s", exc)
        return None


async def lookup_acoustid(fingerprint: str, duration: float) -> dict | None:
    """Look up the fingerprint against AcoustID. Returns the raw response dict.

    Returns None on network error or when the API key is not configured.
    """
    if not settings.acoustid_api_key:
        log.info("AcoustID API key not configured — skipping lookup")
        return None
    params = {
        "format": "json",
        "client": settings.acoustid_api_key,
        "duration": int(max(duration, 1)),
        "fingerprint": fingerprint,
        "meta": "recordings+releasegroups+compress",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(ACOUSTID_LOOKUP_URL, params=params)
        if r.status_code != 200:
            log.warning("AcoustID HTTP %d: %s", r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as exc:
        log.warning("AcoustID lookup failed: %s", exc)
        return None


def _parse_lookup_response(resp: dict) -> dict:
    """Convert the AcoustID response into a clean summary dict.

    Returns:
      {
        "score": float,                # best match score 0-1
        "matches": [{score, recording_id, title, artist, release, year}],
        "clean": bool,                 # True if score < threshold
      }
    """
    results = resp.get("results") or []
    if not results:
        return {"score": 0.0, "matches": [], "clean": True}

    best_score = 0.0
    out_matches: list[dict] = []
    for r in results:
        score = float(r.get("score", 0.0))
        if score > best_score:
            best_score = score
        recordings = r.get("recordings") or []
        if not recordings:
            continue
        # Take the top recording for this result.
        rec = recordings[0]
        release_groups = rec.get("releasegroups") or []
        release_title = release_groups[0].get("title") if release_groups else ""
        out_matches.append({
            "score": round(score, 3),
            "recording_id": rec.get("id", ""),
            "title": rec.get("title", ""),
            "artist": ", ".join(a.get("name", "") for a in (rec.get("artists") or [])[:2]),
            "release": release_title,
            "year": release_groups[0].get("year") if release_groups else None,
        })

    # Sort matches by score desc.
    out_matches.sort(key=lambda m: m["score"], reverse=True)
    threshold = settings.copyright_score_threshold
    clean = best_score < threshold
    return {
        "score": round(best_score, 3),
        "matches": out_matches[:5],
        "clean": clean,
    }


async def check_video(video_path: str | Path) -> dict:
    """Run the full pre-upload copyright check on a rendered video.

    Returns:
      {
        "checked": bool,             # False when skipped (no fpcalc / no API key)
        "clean": bool,               # True when no high-score match
        "score": float,
        "matches": [...],
        "audio_path": str,
        "reason": str,               # human-readable explanation
      }
    """
    out: dict[str, Any] = {
        "checked": False, "clean": True, "score": 0.0,
        "matches": [], "audio_path": "", "reason": "",
    }
    video = Path(video_path)
    if not video.exists():
        out["reason"] = f"video file not found: {video_path}"
        return out

    if not settings.pre_upload_copyright_check:
        out["reason"] = "pre-upload copyright check disabled in settings"
        return out

    if not fpcalc_available():
        out["reason"] = "fpcalc (chromaprint) not installed — skipping fingerprint"
        log.warning(out["reason"])
        return out

    if not settings.acoustid_api_key:
        out["reason"] = "ACOUSTID_API_KEY not set — skipping lookup"
        log.warning(out["reason"])
        return out

    # Step 1: extract audio.
    wav_path = video.parent / f"{video.stem}_copyright.wav"
    if not await extract_audio(video, wav_path):
        out["reason"] = "audio extraction failed"
        return out
    out["audio_path"] = str(wav_path)

    # Step 2: compute fingerprint.
    fp = await compute_fingerprint(wav_path)
    if fp is None or not fp.get("fingerprint"):
        out["reason"] = "fingerprint computation failed"
        return out

    # Step 3: lookup against AcoustID.
    resp = await lookup_acoustid(fp["fingerprint"], fp["duration"])
    if resp is None:
        out["reason"] = "AcoustID lookup failed (network / API)"
        return out

    parsed = _parse_lookup_response(resp)
    out.update({
        "checked": True,
        "clean": parsed["clean"],
        "score": parsed["score"],
        "matches": parsed["matches"],
        "reason": (
            f"clean (no match above {settings.copyright_score_threshold:.2f})"
            if parsed["clean"]
            else f"flagged: top match score {parsed['score']:.2f} "
                 f"({parsed['matches'][0]['title'] if parsed['matches'] else 'unknown'})"
        ),
    })
    log.info("copyright check on %s: %s", video.name, out["reason"])
    return out
