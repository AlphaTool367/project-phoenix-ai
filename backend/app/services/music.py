"""Copyright-safe music: Jamendo API with synthesized ambient fallback."""
from __future__ import annotations

import math
from pathlib import Path

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd

log = get_logger("music")

NICHE_MOODS = {
    "technology": "electronic ambient",
    "finance": "corporate calm",
    "health": "acoustic chill",
    "space": "ambient cinematic",
    "history": "cinematic orchestral",
    "science": "ambient documentary",
}


async def _jamendo(mood: str, dest: Path, min_seconds: float) -> dict | None:
    if not settings.jamendo_available:
        return None
    try:
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
            r = await client.get(
                "https://api.jamendo.com/v3.0/tracks/",
                params={
                    "client_id": settings.jamendo_client_id,
                    "format": "json", "limit": 10,
                    "tags": mood, "order": "popularity_total",
                    "audioformat": "mp32",
                    "durationbetween": f"{int(min_seconds)}-600",
                },
            )
            r.raise_for_status()
            for track in r.json().get("results", []):
                url = track.get("audiodownload") or track.get("audio")
                if not url:
                    continue
                async with client.stream("GET", url) as dl:
                    dl.raise_for_status()
                    with open(dest, "wb") as fh:
                        async for chunk in dl.aiter_bytes(1 << 16):
                            fh.write(chunk)
                if dest.stat().st_size > 50_000:
                    return {
                        "path": str(dest), "provider": "jamendo",
                        "title": track.get("name", ""), "artist": track.get("artist_name", ""),
                        "license": "Jamendo royalty-free (CC)",
                    }
    except Exception as exc:
        log.warning("jamendo failed: %s", exc)
    return None


async def _synth_bed(dest: Path, seconds: float, mood: str) -> dict:
    """Layered sine-pad ambient bed, generated with FFmpeg alone."""
    base = 110.0 if "calm" in mood or "ambient" in mood else 130.0
    fade_out_start = max(seconds - 4, 1)
    graph = (
        f"[1:a]volume=0.5[b];[2:a]volume=0.3[c];"
        f"[0:a][b][c]amix=inputs=3:normalize=0,"
        f"volume=0.16,lowpass=f=600,tremolo=f=0.12:d=0.5,"
        f"afade=t=in:d=3,afade=t=out:st={fade_out_start:.1f}:d=3[a]"
    )
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y",
        "-f", "lavfi", "-i", f"sine=frequency={base}:duration={seconds + 1}",
        "-f", "lavfi", "-i", f"sine=frequency={base * 1.5}:duration={seconds + 1}",
        "-f", "lavfi", "-i", f"sine=frequency={base * 2.02}:duration={seconds + 1}",
        "-filter_complex", graph,
        "-map", "[a]", "-ar", "44100", "-ac", "2", "-t", f"{seconds:.1f}", str(dest),
    ])
    if rc != 0:
        raise RuntimeError(f"music synth failed: {err[:300]}")
    return {"path": str(dest), "provider": "synthesized",
            "title": "Phoenix Ambient Bed", "artist": "Project Phoenix AI", "license": "original"}


async def pick_music(niche: str, seconds: float, video_id: int) -> dict:
    mood = NICHE_MOODS.get(niche, "ambient documentary")
    dest = settings.path(settings.data_dir, "music") / f"v{video_id}_bed.mp3"
    got = await _jamendo(mood, dest, min(seconds, 180))
    if got:
        log.info("music from Jamendo: '%s' by %s", got["title"], got["artist"])
        return got
    log.info("Jamendo unavailable — synthesizing ambient bed (%.0fs)", seconds)
    return await _synth_bed(dest, seconds, mood)
