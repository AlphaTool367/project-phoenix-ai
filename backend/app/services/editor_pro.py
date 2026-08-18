"""Editor Pro — advanced editing features.

  - Beat-sync cuts: detect audio beats and align scene cuts to them.
  - Custom intro/outro maker: generate animated brand intro/outro clips.
  - Split screen / Picture-in-Picture: talking head + b-roll side by side.
  - Instagram carousel: convert video scenes into swipeable image carousel.
  - GPU acceleration: use NVENC for faster rendering when available.

All features use free tools (librosa for beat detection, Pillow + FFmpeg
for intro/outro and carousel, FFmpeg for split screen, NVENC for GPU).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd
from PIL import Image, ImageDraw, ImageFont

log = get_logger("editor_pro")


# ----------------------------------------------------- beat-sync cuts

async def detect_beats(audio_path: str, max_beats: int = 20) -> list[float]:
    """Detect beat timestamps in an audio file using librosa.

    Returns a list of timestamps (in seconds) where beats occur.
    Falls back to evenly-spaced beats when librosa isn't installed.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        log.warning("librosa not installed — using evenly-spaced beats")
        duration = await probe_duration(audio_path) or 30.0
        step = duration / max_beats
        return [step * i for i in range(1, max_beats)]
    try:
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        return beat_times[:max_beats]
    except Exception as exc:
        log.warning("beat detection failed: %s", exc)
        duration = await probe_duration(audio_path) or 30.0
        step = duration / max_beats
        return [step * i for i in range(1, max_beats)]


async def align_scenes_to_beats(scene_durations: list[float],
                                 beats: list[float]) -> list[float]:
    """Adjust scene durations so cuts land on the nearest beat.

    Returns adjusted durations that sum to approximately the same total
    but with cuts aligned to beats.
    """
    if not beats or not scene_durations:
        return scene_durations
    adjusted = []
    cursor = 0.0
    for i, dur in enumerate(scene_durations):
        target = cursor + dur
        # Find the nearest beat to `target`.
        nearest = min(beats, key=lambda b: abs(b - target))
        new_dur = max(2.0, nearest - cursor)
        adjusted.append(new_dur)
        cursor += new_dur
    return adjusted


# ----------------------------------------------------- custom intro/outro

def _load_font(px: int) -> ImageFont.FreeTypeFont:
    fonts_dir = settings.assets_path / "fonts"
    if fonts_dir.exists():
        for f in sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf")):
            try:
                return ImageFont.truetype(str(f), px)
            except OSError:
                continue
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, px)
        except OSError:
            continue
    return ImageFont.load_default()


async def generate_intro(channel_name: str, out_path: Path,
                          duration: float = 3.0) -> str:
    """Generate an animated brand intro clip (3 seconds, logo + channel name).

    Uses Pillow to render frames + FFmpeg to assemble them into a video.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 1920, 1080
    frames_dir = out_path.parent / f"{out_path.stem}_frames"
    frames_dir.mkdir(exist_ok=True)

    # Generate 30 frames (3 sec at 10fps — keep it light).
    n_frames = max(int(duration * 10), 10)
    for i in range(n_frames):
        img = Image.new("RGB", (w, h), (10, 10, 18))
        d = ImageDraw.Draw(img)
        # Animated gradient bar that slides in.
        bar_w = int(w * (i / n_frames))
        d.rectangle([0, h // 2 - 80, bar_w, h // 2 + 80],
                    fill=(255, 94, 58))
        # Channel name text.
        font = _load_font(80)
        text = channel_name.upper()
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        d.text(((w - tw) / 2, h // 2 - 40), text, font=font,
               fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
        img.save(frames_dir / f"frame_{i:04d}.png")

    # Assemble frames into a video.
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-framerate", "10", "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-t", f"{duration:.1f}",
        str(out_path),
    ])
    if rc != 0:
        log.warning("intro generation failed: %s", err[-200:])
        return ""
    log.info("generated intro: %s", out_path.name)
    return str(out_path)


async def generate_outro(channel_name: str, out_path: Path,
                          duration: float = 4.0) -> str:
    """Generate an outro clip with 'Subscribe' CTA."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 1920, 1080
    frames_dir = out_path.parent / f"{out_path.stem}_frames"
    frames_dir.mkdir(exist_ok=True)
    n_frames = max(int(duration * 10), 10)

    for i in range(n_frames):
        img = Image.new("RGB", (w, h), (10, 10, 18))
        d = ImageDraw.Draw(img)
        # Fade-in subscribe text.
        alpha = min(i / (n_frames * 0.4), 1.0)
        font_big = _load_font(120)
        font_small = _load_font(60)
        text = "SUBSCRIBE"
        bbox = d.textbbox((0, 0), text, font=font_big)
        tw = bbox[2] - bbox[0]
        d.text(((w - tw) / 2, h // 2 - 80), text, font=font_big,
               fill=(int(255 * alpha), int(94 * alpha), int(58 * alpha)))
        sub_text = f"for more from {channel_name}"
        bbox2 = d.textbbox((0, 0), sub_text, font=font_small)
        tw2 = bbox2[2] - bbox2[0]
        d.text(((w - tw2) / 2, h // 2 + 60), sub_text, font=font_small,
               fill=(int(200 * alpha), int(200 * alpha), int(200 * alpha)))
        img.save(frames_dir / f"frame_{i:04d}.png")

    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-framerate", "10", "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-t", f"{duration:.1f}",
        str(out_path),
    ])
    if rc != 0:
        log.warning("outro generation failed: %s", err[-200:])
        return ""
    log.info("generated outro: %s", out_path.name)
    return str(out_path)


# ----------------------------------------------------- split screen / PiP

async def create_split_screen(clip_a: str, clip_b: str, out_path: Path,
                               layout: str = "side_by_side") -> str:
    """Combine two clips into a split-screen or picture-in-picture video.

    layout: 'side_by_side' | 'pip' (picture-in-picture, B is small overlay)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if layout == "pip":
        # Picture-in-picture: B is a small overlay in the bottom-right.
        vf = ("[0:v]scale=1920:1080[bg];"
              "[1:v]scale=480:270[fg];"
              "[bg][fg]overlay=W-w-40:H-h-40[vout]")
    else:
        # Side by side.
        vf = ("[0:v]scale=960:1080[left];"
              "[1:v]scale=960:1080[right];"
              "[left][right]hstack[vout]")
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", clip_a, "-i", clip_b,
        "-filter_complex", vf,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out_path),
    ])
    if rc != 0:
        log.warning("split screen failed: %s", err[-200:])
        return ""
    return str(out_path)


# ----------------------------------------------------- Instagram carousel

async def video_to_instagram_carousel(video_path: str, scene_count: int = 5,
                                       out_dir: Path | None = None) -> list[str]:
    """Extract key frames from a video and save them as Instagram carousel images
    (1080x1080 square, suitable for swipeable posts).

    Returns a list of image file paths.
    """
    src = Path(video_path)
    if not src.exists():
        return []
    out_dir = out_dir or src.parent / f"{src.stem}_carousel"
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = await probe_duration(video_path) or 30.0
    step = duration / (scene_count + 1)
    paths = []
    for i in range(scene_count):
        ts = step * (i + 1)
        frame_path = out_dir / f"carousel_{i+1}.jpg"
        rc, _, _ = await run_cmd([
            ffmpeg_bin(), "-y", "-ss", f"{ts:.2f}", "-i", str(src),
            "-frames:v", "1", "-q:v", "3",
            "-vf", "scale=1080:1080:force_original_aspect_ratio=increase,"
                   "crop=1080:1080",
            str(frame_path),
        ])
        if rc == 0 and frame_path.exists():
            paths.append(str(frame_path))
    log.info("generated %d carousel images from %s", len(paths), src.name)
    return paths


# ----------------------------------------------------- GPU acceleration

def gpu_encoder_available() -> str | None:
    """Check if a GPU hardware encoder is available (NVENC for NVIDIA,
    VideoToolbox for macOS, AMF for AMD).

    Returns the encoder name (e.g. 'h264_nvenc') or None.
    """
    import shutil
    encoders = [
        ("h264_nvenc", "NVIDIA NVENC"),
        ("h264_videotoolbox", "Apple VideoToolbox"),
        ("h264_amf", "AMD AMF"),
        ("h264_qsv", "Intel QuickSync"),
    ]
    for enc, label in encoders:
        try:
            import subprocess
            r = subprocess.run(
                [ffmpeg_bin(), "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=5,
            )
            if enc in r.stdout:
                log.info("GPU encoder available: %s (%s)", enc, label)
                return enc
        except Exception:
            continue
    return None


def get_best_encoder() -> str:
    """Return the best available video encoder (GPU if available, else libx264)."""
    gpu = gpu_encoder_available()
    return gpu or "libx264"
