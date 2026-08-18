"""Automatic media collection: Pexels + Pixabay, with generated-clip fallback.

Each scene's visual_query is searched; the best-matching clip is downloaded
and cached. Without API keys (or on any failure) Phoenix renders an animated
branded gradient clip locally, so scenes always have footage.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd, slugify

log = get_logger("media")

_HEADERS = {"User-Agent": "ProjectPhoenixAI/1.0"}


async def _download(url: str, dest: Path) -> bool:
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=_HEADERS) as r:
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    async for chunk in r.aiter_bytes(1 << 16):
                        fh.write(chunk)
        return dest.stat().st_size > 10_000
    except Exception as exc:
        log.warning("media download failed: %s", exc)
        return False


async def _pexels(query: str, dest: Path) -> dict | None:
    if not settings.pexels_available:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "per_page": 5, "orientation": "landscape"},
                headers={"Authorization": settings.pexels_api_key, **_HEADERS},
            )
            r.raise_for_status()
            for video in r.json().get("videos", []):
                files = sorted(
                    video.get("video_files", []),
                    key=lambda f: abs((f.get("height") or 0) - 1080),
                )
                for f in files:
                    if f.get("link") and (f.get("height") or 0) >= 540:
                        if await _download(f["link"], dest):
                            return {"path": str(dest), "provider": "pexels",
                                    "attribution": video.get("user", {}).get("name", "")}
    except Exception as exc:
        log.warning("pexels search failed: %s", exc)
    return None


async def _pixabay(query: str, dest: Path) -> dict | None:
    if not settings.pixabay_available:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://pixabay.com/api/videos/",
                params={"key": settings.pixabay_api_key, "q": query,
                        "per_page": 5, "video_type": "film"},
                headers=_HEADERS,
            )
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                vids = hit.get("videos", {})
                pick = vids.get("large") or vids.get("medium") or vids.get("small")
                if pick and pick.get("url"):
                    if await _download(pick["url"], dest):
                        return {"path": str(dest), "provider": "pixabay",
                                "attribution": hit.get("user", "")}
    except Exception as exc:
        log.warning("pixabay search failed: %s", exc)
    return None


# ---------------------------------------------------------------- fallback
_PALETTES = [
    ((255, 94, 58), (72, 12, 94)),   # phoenix ember -> violet
    ((24, 144, 255), (9, 9, 62)),    # electric blue -> midnight
    ((255, 195, 18), (94, 31, 9)),   # gold -> ember brown
    ((46, 213, 115), (6, 48, 46)),   # teal green -> deep sea
    ((235, 77, 152), (42, 8, 69)),   # magenta -> plum
]


async def _generated_clip(query: str, dest: Path, duration: float, size: tuple[int, int]) -> dict:
    """Procedural animated clip: gradient + drifting light orbs + slow zoom."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    seed = int(hashlib.sha256(query.encode()).hexdigest(), 16) % (2**32)
    c1, c2 = _PALETTES[seed % len(_PALETTES)]

    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = (np.array(c1, dtype=np.float32) * (1 - t)
            + np.array(c2, dtype=np.float32) * t)
    img = Image.fromarray(
        np.broadcast_to(grad, (h, w, 3)).astype(np.uint8), "RGB")

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    import random as _rnd
    rng = _rnd.Random(seed)
    for _ in range(6):
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        r = rng.randint(w // 10, w // 4)
        od.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=(255, 255, 255, rng.randint(14, 40)))
    overlay = overlay.filter(ImageFilter.GaussianBlur(w // 12))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    frame = dest.with_suffix(".png")
    img.save(frame)
    frames = max(int(duration * 30), 30)
    zoom_expr = "min(zoom+0.0009,1.35)"
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", str(frame),
        "-vf", (f"scale={w * 2}:{h * 2},zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30"),
        "-t", f"{duration:.2f}", "-pix_fmt", "yuv420p", str(dest),
    ])
    frame.unlink(missing_ok=True)
    if rc != 0:
        raise RuntimeError(f"generated clip failed: {err[:300]}")
    return {"path": str(dest), "provider": "generated", "attribution": ""}


async def fetch_scene_clip(
    query: str, video_id: int, scene_index: int, duration: float,
    size: tuple[int, int],
) -> dict:
    """Find the best clip for one scene — stock first, generated fallback.

    v1.7 fix: include a hash of the query in the filename so different
    queries for the same scene_index produce DIFFERENT cached files. The
    old slugify(query, 30) was truncating queries to 30 chars, which meant
    similar queries ("history a cinematic", "history the cinematic")
    collapsed to the same file → every scene showed the same clip.
    """
    import hashlib
    cache = settings.path(settings.data_dir, "media")
    # Hash the query so different queries → different files, even when the
    # slugified prefix is identical.
    query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
    slug = slugify(query, 40)
    dest = cache / f"v{video_id}_s{scene_index}_{slug}_{query_hash}.mp4"
    if dest.exists() and dest.stat().st_size > 10_000:
        log.info("scene %d media via cache for '%s' (hash=%s)", scene_index, query, query_hash)
        return {"path": str(dest), "provider": "cache", "attribution": ""}

    for provider in (_pexels, _pixabay):
        got = await provider(query, dest)
        if got:
            log.info("scene %d media via %s for '%s'", scene_index, got["provider"], query)
            return got

    log.info("scene %d: generating branded clip for '%s'", scene_index, query)
    return await _generated_clip(query, dest, duration, size)
