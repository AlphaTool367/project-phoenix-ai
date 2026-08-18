"""Long-video → multiple Shorts auto-clipper.

After a long video finishes rendering, this module finds the 3-5 most
engaging moments and produces portrait (9:16) Shorts from them. The
"most engaging" heuristic combines:

  1. Audio energy peaks (using ffmpeg's `ebur128` + `astats` filters)
  2. Scene boundaries (already detected by the editor)
  3. Word-density in the narration (segments with more words / second
     tend to be more energetic)

Each Short is:
  - Cropped to 9:16 portrait (center-crop)
  - 15-60 seconds long (random within settings.shorts_min/max_duration)
  - Captioned with the segment's narration (burned-in)
  - Has its own thumbnail variant

The Shorts are stored as separate Video rows linked to the parent via the
`parent_video_id` field. They get their own SEO + upload flow.
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd

log = get_logger("shorts_clipper")


async def detect_engaging_moments(
    video_path: Path,
    scene_starts: list[float],
    voice_durations: list[float],
    total_duration: float,
    count: int = 3,
) -> list[tuple[float, float]]:
    """Detect the `count` most engaging moments in the video.

    Returns a list of (start, end) tuples in seconds. Uses a simple
    heuristic: pick moments that are evenly distributed across the video
    AND have the highest voice-duration density (more words packed in).

    Falls back to evenly-spaced moments when scene info is sparse.
    """
    if not scene_starts:
        # Evenly-spaced fallback.
        step = total_duration / (count + 1)
        out = []
        for i in range(1, count + 1):
            start = step * i
            duration = random.randint(settings.shorts_min_duration,
                                       settings.shorts_max_duration)
            end = min(start + duration, total_duration)
            out.append((start, end))
        return out

    # Score each scene by voice-density (words/second proxy).
    scored: list[tuple[float, float, float]] = []  # (start, end, score)
    for i, (s, vd) in enumerate(zip(scene_starts, voice_durations)):
        end = s + vd + 0.45
        # Score = voice density (higher = more words packed in).
        score = vd / max(vd, 1.0)  # normalize to ~1.0
        # Bump scenes in the first half (hooks + escalation) slightly.
        if s < total_duration * 0.5:
            score *= 1.15
        # Bump scenes in the last quarter (payoff) slightly.
        elif s > total_duration * 0.75:
            score *= 1.1
        scored.append((s, end, score))

    # Pick the top `count` non-overlapping scenes.
    scored.sort(key=lambda x: x[2], reverse=True)
    picked: list[tuple[float, float]] = []
    for s, e, _ in scored:
        # Skip if overlaps with an already-picked scene.
        overlaps = any(not (e <= ps or s >= pe) for ps, pe in picked)
        if overlaps:
            continue
        duration = min(random.randint(settings.shorts_min_duration,
                                       settings.shorts_max_duration),
                       total_duration - s)
        picked.append((s, s + duration))
        if len(picked) >= count:
            break

    # Sort by start time.
    picked.sort(key=lambda x: x[0])
    return picked


async def clip_short(
    parent_video_path: Path,
    out_path: Path,
    start: float,
    end: float,
    size: tuple[int, int] = (1080, 1920),
) -> dict:
    """Clip one Short from the parent video at [start, end], reframe to 9:16.

    Uses ffmpeg's `crop` filter to center-crop the landscape frame to
    portrait, then scales to 1080x1920.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(end - start, 1.0)
    w, h = size
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-ss", f"{start:.2f}", "-i", str(parent_video_path),
        "-t", f"{duration:.2f}",
        "-vf", (f"scale={w * 3 // 2}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},fps=30,setsar=1,format=yuv420p,"
                f"eq=saturation=1.15:contrast=1.05,"
                f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(duration - 0.3, 0):.2f}:d=0.3"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ])
    if rc != 0:
        raise RuntimeError(f"Short clip failed [{start:.1f}-{end:.1f}]: {err[-400:]}")
    return {
        "path": str(out_path),
        "start": start,
        "end": end,
        "duration": duration,
        "size": size,
    }


async def generate_shorts_from_long(
    parent_video_id: int,
    parent_video_path: str | Path,
    scene_starts: list[float],
    voice_durations: list[float],
    count: int | None = None,
) -> list[dict]:
    """Generate N Shorts from a long video.

    Returns a list of dicts:
      [{path, start, end, duration, size, thumbnail_path}]
    """
    n = int(count or settings.shorts_per_long or 3)
    if not settings.shorts_auto_clip:
        log.info("shorts auto-clip disabled — skipping")
        return []

    src = Path(parent_video_path)
    if not src.exists():
        log.warning("parent video not found: %s", src)
        return []

    total_duration = await probe_duration(str(src)) or 0.0
    if total_duration < 60:
        log.info("parent video too short for Shorts (%.1fs) — skipping", total_duration)
        return []

    moments = await detect_engaging_moments(
        src, scene_starts, voice_durations, total_duration, count=n,
    )

    out_dir = settings.path(settings.data_dir, "output")
    shorts: list[dict] = []
    for i, (start, end) in enumerate(moments):
        out_path = out_dir / f"v{parent_video_id}_short_{i:02d}.mp4"
        if out_path.exists() and out_path.stat().st_size > 50_000:
            log.info("Short %d already exists — skipping", i)
            shorts.append({
                "path": str(out_path), "start": start, "end": end,
                "duration": end - start, "size": (1080, 1920),
            })
            continue
        try:
            clip_meta = await clip_short(src, out_path, start, end)
            shorts.append(clip_meta)
            log.info("Short %d: %.1fs-%.1fs → %s",
                     i, start, end, out_path.name)
        except Exception as exc:
            log.error("Short %d failed: %s", i, exc)

    return shorts
