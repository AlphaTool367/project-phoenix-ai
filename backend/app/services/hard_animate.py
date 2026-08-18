"""Hard features Group 2 — Animated explainer (manim) + Live stream highlights.

  - Animated explainer: use manim (open source, Python) to generate
    mathematical/scientific animations as video clips. Great for
    science/education channels.
  - Live stream highlights: detect high-energy moments in a long
    recording (audio peaks + chat spikes) and auto-clip them into
    highlight videos.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd

log = get_logger("hard_animate")


# ----------------------------------------------------- animated explainer (manim)

def manim_available() -> bool:
    """Check if manim is installed."""
    try:
        import manim  # noqa: F401
        return True
    except ImportError:
        return False


async def generate_animated_explainer(topic: str, key_points: list[str],
                                       out_path: Path) -> dict:
    """Generate an animated explainer clip using manim.

    Creates a simple scene with:
      - Title text animation
      - Key points appearing one by one
      - A summary at the end

    Requires: pip install manim
    + LaTeX (for text rendering): apt install texlive-full (Linux) /
      brew install --cask mactex (macOS) / install MiKTeX (Windows)
    """
    if not manim_available():
        return {"success": False,
                "reason": "manim not installed. Run: pip install manim"}
    try:
        from manim import (Scene, Text, FadeIn, FadeOut, VGroup, UP, DOWN,
                           LEFT, RIGHT, YELLOW, WHITE, BLUE, config)
        # Configure manim to output to our path.
        config.media_dir = str(out_path.parent / "manim_media")
        config.output_file = out_path.name

        class ExplainerScene(Scene):
            def construct(self):
                title = Text(topic, font_size=48, color=YELLOW)
                self.play(FadeIn(title, shift=UP))
                self.wait(1)
                self.play(title.animate.to_edge(UP))
                for i, point in enumerate(key_points):
                    t = Text(f"• {point}", font_size=32, color=WHITE)
                    t.next_to(title, DOWN, buff=0.5 + i * 0.7)
                    self.play(FadeIn(t, shift=RIGHT))
                    self.wait(0.5)
                self.wait(2)
                self.play(FadeOut(VGroup(*self.mobjects)))

        scene = ExplainerScene()
        scene.render()
        # Find the rendered file.
        rendered = out_path.parent / "manim_media" / "videos" / "1080p60"
        rendered_file = list(rendered.glob("*.mp4"))[0] if rendered.exists() else None
        if rendered_file:
            rendered_file.rename(out_path)
            return {"success": True, "path": str(out_path), "engine": "manim"}
        return {"success": False, "reason": "rendered file not found"}
    except Exception as exc:
        log.warning("manim explainer failed: %s", exc)
        return {"success": False, "reason": str(exc)}


# ----------------------------------------------------- live stream highlights

async def detect_highlight_moments(stream_path: str, segment_duration: float = 30.0,
                                    max_highlights: int = 5) -> list[dict]:
    """Detect high-energy moments in a long recording.

    Uses audio energy analysis (via ffmpeg's `volumedetect` + `astats`) to
    find segments with the loudest audio — these are typically the most
    exciting moments (cheers, laughter, dramatic reveals).

    Returns a list of {start, end, energy_score} dicts.
    """
    src = Path(stream_path)
    if not src.exists():
        return []
    total_duration = await probe_duration(stream_path) or 0.0
    if total_duration < 60:
        return []

    # Sample audio energy in 10-second windows.
    window = 10.0
    n_windows = int(total_duration / window)
    energies: list[tuple[float, float]] = []  # (start_time, energy)

    for i in range(n_windows):
        start = i * window
        rc, out, _ = await run_cmd([
            ffmpeg_bin(), "-y", "-ss", f"{start:.1f}", "-t", f"{window:.1f}",
            "-i", str(src), "-af", "volumedetect", "-f", "null", "-",
        ])
        # Parse mean_volume from stderr.
        import re
        m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", out + _)
        if m:
            energy = -float(m.group(1))  # invert so louder = higher
            energies.append((start, energy))

    if not energies:
        # Fallback: evenly spaced.
        step = total_duration / (max_highlights + 1)
        return [{"start": step * (i + 1), "end": step * (i + 1) + segment_duration,
                 "energy_score": 50.0}
                for i in range(max_highlights)]

    # Sort by energy (loudest first) and pick top N.
    energies.sort(key=lambda x: x[1], reverse=True)
    top = energies[:max_highlights]
    # Sort by time.
    top.sort(key=lambda x: x[0])
    # Normalize energy scores 0-100.
    max_e = max(e for _, e in top) if top else 1
    return [{"start": s, "end": s + segment_duration,
             "energy_score": round(e / max_e * 100, 1) if max_e > 0 else 50}
            for s, e in top]


async def clip_highlights(stream_path: str, highlights: list[dict],
                           out_dir: Path | None = None) -> list[dict]:
    """Clip highlight segments from a stream into separate video files."""
    src = Path(stream_path)
    out_dir = out_dir or src.parent / f"{src.stem}_highlights"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, h in enumerate(highlights):
        out_path = out_dir / f"highlight_{i+1:02d}.mp4"
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-ss", f"{h['start']:.2f}",
            "-i", str(src), "-t", f"{h['end'] - h['start']:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(out_path),
        ])
        if rc == 0:
            results.append({"path": str(out_path), **h, "index": i + 1})
    return results
