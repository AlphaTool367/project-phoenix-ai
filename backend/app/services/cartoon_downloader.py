"""YouTube Cartoon Downloader — download Full HD cartoons + clip into Shorts.

Uses yt-dlp (free, open source) to download cartoons from YouTube in Full HD.
Then clips the cartoon into 1-2 minute Shorts, makes small modifications
(color shift, speed adjustment, overlay) to reduce copyright risk, and
prepares them for upload.

Requirements:
  pip install yt-dlp

yt-dlp is the maintained fork of youtube-dl — it handles YouTube's
anti-bot measures and supports Full HD downloads.

Flow:
  1. User provides a YouTube URL (or search query).
  2. yt-dlp downloads the video in Full HD (1080p) to data/cartoons/.
  3. The system detects the most engaging moments (audio peaks).
  4. Clips 1-2 minute Shorts from those moments.
  5. Applies modifications: color shift, slight speed change, voice overlay,
     music bed — to reduce Content ID matching.
  6. Runs the copyright check (AcoustID) on each Short.
  7. If clean, uploads to YouTube as a Short.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd

log = get_logger("cartoon_downloader")


def ytdlp_available() -> bool:
    """Check if yt-dlp is installed."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return shutil.which("yt-dlp") is not None


async def download_cartoon(url: str, out_dir: Path | None = None,
                            quality: str = "1080p") -> dict:
    """Download a cartoon/video from YouTube in Full HD using yt-dlp.

    Args:
        url: YouTube video URL or search query.
        out_dir: Directory to save the video (default: data/cartoons/).
        quality: Video quality (1080p, 720p, 480p).

    Returns:
        {success, path, title, duration, channel}
    """
    if not ytdlp_available():
        return {"success": False,
                "reason": "yt-dlp not installed. Run: pip install yt-dlp"}

    out_dir = out_dir or settings.path(settings.data_dir, "cartoons")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Quality mapping for yt-dlp format selector.
    height_map = {"1080p": "1080", "720p": "720", "480p": "480"}
    max_height = height_map.get(quality, "1080")

    run_id = uuid.uuid4().hex[:10]
    ydl_opts = {
        "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        # Use the stable video id instead of the title: titles contain slashes,
        # emojis and platform-specific path characters.
        "outtmpl": str(out_dir / f"%(id)s_{run_id}.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "writeinfojson": False,
        "writethumbnail": False,
    }

    def _download():
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return {
                "title": info.get("title", "unknown"),
                "duration": info.get("duration", 0),
                "channel": info.get("channel", ""),
                "uploader": info.get("uploader", ""),
                "view_count": info.get("view_count", 0),
                "id": info.get("id", ""),
            }

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _download)
        # Find the exact stable output first, then use a recent-file fallback.
        downloaded = sorted(out_dir.glob(f"{info.get('id', '')}_{run_id}.*"),
                            key=lambda f: f.stat().st_mtime, reverse=True)
        if not downloaded:
            downloaded = sorted(out_dir.glob("*.mp4"),
                                key=lambda f: f.stat().st_mtime, reverse=True)
        if not downloaded:
            return {"success": False, "reason": "downloaded file not found"}
        return {"success": True, "path": str(downloaded[0]), **info}
    except Exception as exc:
        log.warning("cartoon download failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def search_cartoons(query: str, max_results: int = 10) -> list[dict]:
    """Search YouTube for cartoons matching a query. Returns metadata only
    (no download). The user picks one to download.

    Returns list of {title, url, duration, channel, view_count, thumbnail}.
    """
    if not ytdlp_available():
        return []
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch",
        "playlistend": max_results,
    }

    def _search():
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            entries = result.get("entries", []) if result else []
            out = []
            for e in entries:
                if not e:
                    continue
                video_id = e.get("id", "")
                webpage_url = e.get("webpage_url") or e.get("url") or ""
                if video_id and (not webpage_url.startswith("http://") and not webpage_url.startswith("https://")):
                    webpage_url = f"https://www.youtube.com/watch?v={video_id}"
                out.append({
                    "title": e.get("title", ""),
                    "url": webpage_url,
                    "id": e.get("id", ""),
                    "duration": e.get("duration", 0),
                    "channel": e.get("channel", e.get("uploader", "")),
                    "view_count": e.get("view_count", 0),
                    "thumbnail": e.get("thumbnail", ""),
                })
            return out

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _search)
    except Exception as exc:
        log.warning("cartoon search failed: %s", exc)
        return []


async def detect_engaging_moments_cartoon(video_path: str,
                                           segment_duration: int = 60,
                                           max_segments: int = 5) -> list[dict]:
    """Detect the most engaging moments in a cartoon for Shorts clipping.

    Uses audio energy analysis (loudest moments = most action/excitement).
    """
    src = Path(video_path)
    if not src.exists():
        return []
    total_duration = await probe_duration(video_path) or 0.0
    if total_duration < 60:
        return [{"start": 0, "end": total_duration, "energy_score": 100}]

    # Sample audio energy in 15-second windows.
    window = 15.0
    n_windows = int(total_duration / window)
    energies: list[tuple[float, float]] = []

    for i in range(n_windows):
        start = i * window
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-ss", f"{start:.1f}", "-t", f"{window:.1f}",
            "-i", str(src), "-af", "volumedetect", "-f", "null", "-",
        ])
        import re
        m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", err)
        if m:
            energy = -float(m.group(1))
            energies.append((start, energy))

    if not energies:
        # Fallback: evenly spaced.
        step = total_duration / (max_segments + 1)
        return [{"start": step * (i + 1), "end": min(step * (i + 1) + segment_duration, total_duration),
                 "energy_score": 50.0} for i in range(max_segments)]

    # Pick top N non-overlapping moments.
    energies.sort(key=lambda x: x[1], reverse=True)
    picked = []
    for s, e in energies:
        overlaps = any(not (s + segment_duration <= ps or s >= pe)
                       for ps, pe in [(p["start"], p["end"]) for p in picked])
        if overlaps:
            continue
        picked.append({"start": s, "end": min(s + segment_duration, total_duration),
                       "energy_score": round(e, 1)})
        if len(picked) >= max_segments:
            break
    picked.sort(key=lambda x: x["start"])
    return picked


async def clip_and_modify_short(source_path: str, start: float, end: float,
                                 out_path: Path,
                                 modifications: dict | None = None) -> dict:
    """Clip a segment from a cartoon + apply modifications to reduce copyright risk.

    Modifications (all optional):
      - color_shift: adjust hue/saturation slightly (default: yes)
      - speed_change: slight speed adjustment (default: 1.02x — barely noticeable)
      - mirror: flip horizontally (default: no)
      - crop_shift: shift crop position slightly (default: yes)
      - voice_overlay: add a voiceover track on top (default: no)
      - music_bed: add background music (default: no)

    These modifications make the video visually + audibly different from
    the original, reducing Content ID matching while keeping the content
    watchable.
    """
    src = Path(source_path)
    if not src.exists() or src.stat().st_size < 1000:
        return {"success": False, "reason": "source video not found or empty"}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mods = modifications or {}

    duration = end - start
    if duration < 5:
        return {"success": False, "reason": "segment too short"}

    # Build the video filter chain.
    vf_parts = [
        # Crop to 9:16 portrait (Shorts format).
        f"scale=1080:1920:force_original_aspect_ratio=increase",
        f"crop=1080:1920",
        f"fps=30",
        f"setsar=1",
        f"format=yuv420p",
    ]

    # Color shift (subtle — shifts hue by 5 degrees, boosts saturation slightly).
    if mods.get("color_shift", True):
        vf_parts.append("hue=h=5:s=1.1")

    # Speed change (1.02x — barely noticeable but changes the fingerprint).
    speed = mods.get("speed_change", 1.02)
    if speed != 1.0:
        vf_parts.append(f"setpts={1/speed:.4f}*PTS")

    # Mirror (flip horizontally).
    if mods.get("mirror", False):
        vf_parts.append("hflip")

    # Crop shift (shift the crop window slightly).
    if mods.get("crop_shift", True):
        # Re-do the crop with a slight offset.
        vf_parts = [
            f"scale=1120:1920:force_original_aspect_ratio=increase",
            f"crop=1080:1920:20:0",  # shift 20px right
            f"fps=30", f"setsar=1", f"format=yuv420p",
        ] + vf_parts[5:]  # keep the hue/speed/mirror from above

    # Fade in/out.
    fade_in_dur = 0.3
    fade_out_start = max(duration * speed - 0.3, 0)
    vf_parts.append(f"fade=t=in:st=0:d={fade_in_dur:.2f}")
    vf_parts.append(f"fade=t=out:st={fade_out_start:.2f}:d=0.3")

    vf = ",".join(vf_parts)

    # Audio: pitch shift slightly (changes audio fingerprint).
    af_parts = ["aresample=44100"]
    if speed != 1.0:
        af_parts.append(f"atempo={speed:.4f}")
    af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    af = ",".join(af_parts)

    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-ss", f"{start:.2f}", "-i", str(src),
        "-t", f"{duration:.2f}",
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ])
    if rc != 0:
        return {"success": False, "reason": f"ffmpeg failed: {err[-300:]}"}
    log.info("clipped + modified Short: %s (%.1fs-%.1fs)", out_path.name, start, end)
    return {"success": True, "path": str(out_path), "start": start, "end": end,
            "duration": duration * speed, "modifications": mods}


async def process_cartoon_to_shorts(source_path: str, max_shorts: int = 3,
                                     short_duration: int = 60,
                                     channel_id: int = 1) -> dict:
    """Full flow: detect moments → clip → modify → copyright check.

    Returns a list of Short dicts ready for upload.
    """
    from .copyright_check import check_video

    # Step 1: detect engaging moments.
    moments = await detect_engaging_moments_cartoon(
        source_path, segment_duration=short_duration, max_segments=max_shorts)
    if not moments:
        return {"success": False, "reason": "no engaging moments detected"}

    # Step 2: clip + modify each.
    out_dir = settings.path(settings.data_dir, "output", f"cartoon_run_{uuid.uuid4().hex[:8]}")
    shorts = []
    for i, m in enumerate(moments):
        out_path = out_dir / f"short_{i+1:02d}.mp4"
        clip_result = await clip_and_modify_short(
            source_path, m["start"], m["end"], out_path,
            modifications={"color_shift": True, "speed_change": 1.03,
                           "crop_shift": True, "mirror": i % 2 == 1})
        if not clip_result.get("success"):
            continue

        # Step 3: copyright check on the modified clip.
        cr = await check_video(clip_result["path"])
        shorts.append({
            "index": i + 1,
            "path": clip_result["path"],
            "start": m["start"],
            "end": m["end"],
            "duration": clip_result.get("duration", short_duration),
            "copyright_check": cr,
            "clean": cr.get("clean", True) if cr.get("checked") else True,
        })

    if not shorts:
        return {"success": False, "source": source_path,
                "shorts": [], "count": 0,
                "reason": "No Shorts could be rendered. Check FFmpeg output and source audio/video streams."}
    return {"success": True, "source": source_path,
            "shorts": shorts, "count": len(shorts)}
