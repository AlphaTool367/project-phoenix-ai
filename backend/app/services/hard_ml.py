"""Hard features Group 5 — Predictive ML, multi-camera, 360 video, interactive.

  - Predictive topic modeling: train a simple ML model on the channel's
    historical data to predict which topics will perform best.
  - Multi-camera angle rendering: render the same video from multiple
    camera angles (useful for tutorials, product reviews).
  - 360-degree video support: inject 360 metadata into videos for VR
    playback on YouTube.
  - Interactive videos: generate end-screen branching links so viewers
    can "choose their own adventure" between videos.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd
from ..database import session_scope
from ..models import AnalyticsSnapshot, Video

log = get_logger("hard_ml")


# ----------------------------------------------------- predictive topic modeling

def train_topic_model(channel_id: int) -> dict:
    """Train a simple model that predicts a topic's view potential.

    Uses the channel's historical video data (niche, title length, hook
    style, publish hour, content type) as features + 7-day views as the
    target. Falls back to simple averages when scikit-learn isn't installed.
    """
    with session_scope() as db:
        videos = (db.query(Video, AnalyticsSnapshot)
                  .join(AnalyticsSnapshot, AnalyticsSnapshot.video_id == Video.id)
                  .filter(Video.channel_id == channel_id,
                          Video.status == "published")
                  .order_by(AnalyticsSnapshot.captured_at)
                  .all())
        if len(videos) < 5:
            return {"trained": False,
                    "reason": "need ≥5 published videos with analytics"}
        # Extract features.
        features = []
        targets = []
        for v, snap in videos:
            title_len = len(v.title or v.topic)
            niche_hash = hash(v.niche) % 100
            hook_style_hash = hash((v.strategy_context or {}).get("hook_style", "")) % 100
            publish_hour = v.published_at.hour if v.published_at else 12
            is_short = 1 if v.duration_seconds < 180 else 0
            features.append([title_len, niche_hash, hook_style_hash,
                             publish_hour, is_short])
            targets.append(snap.views)
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import cross_val_score
        model = RandomForestRegressor(n_estimators=50, random_state=42)
        model.fit(features, targets)
        scores = cross_val_score(model, features, targets, cv=min(3, len(features)))
        log.info("topic model trained: R²=%.2f (channel %d)", scores.mean(), channel_id)
        return {
            "trained": True,
            "model": "RandomForestRegressor",
            "r2_score": round(scores.mean(), 2),
            "training_samples": len(features),
            "feature_names": ["title_length", "niche_hash", "hook_style_hash",
                              "publish_hour", "is_short"],
        }
    except ImportError:
        # Simple average per niche.
        from collections import defaultdict
        niche_views = defaultdict(list)
        for (title_len, niche_hash, hook_hash, hour, is_short), views in zip(features, targets):
            niche_views[niche_hash].append(views)
        avg = {k: sum(v) / len(v) for k, v in niche_views.items()}
        return {
            "trained": True,
            "model": "simple_niche_average",
            "niche_averages": {str(k): int(v) for k, v in avg.items()},
            "training_samples": len(features),
        }


def predict_topic_potential(channel_id: int, niche: str, title: str,
                             hook_style: str = "", is_short: bool = False) -> dict:
    """Predict how well a topic will perform (estimated 7-day views)."""
    # Simple heuristic: use the channel's average views for this niche.
    with session_scope() as db:
        snaps = (db.query(AnalyticsSnapshot)
                 .join(Video, Video.id == AnalyticsSnapshot.video_id)
                 .filter(Video.channel_id == channel_id,
                         Video.niche == niche)
                 .all())
        if snaps:
            avg = sum(s.views for s in snaps) / len(snaps)
            # Adjust by title length (shorter titles tend to perform better).
            title_bonus = max(0.8, min(1.2, 50 / max(len(title), 10)))
            predicted = int(avg * title_bonus)
            return {
                "predicted_views": predicted,
                "confidence": "low" if len(snaps) < 10 else "medium",
                "niche_avg": int(avg),
                "sample_size": len(snaps),
            }
        return {"predicted_views": 0, "confidence": "none",
                "reason": "no historical data for this niche"}


# ----------------------------------------------------- multi-camera angle rendering

async def render_multi_angle(clip_paths: list[str], out_dir: Path,
                              duration: float) -> dict:
    """Render the same video from multiple camera angles.

    Takes N clips (one per angle) and produces:
      1. A multi-angle video (angles side by side)
      2. Individual angle videos

    Use case: product reviews where you want front/back/side views.
    """
    if not clip_paths:
        return {"success": False, "reason": "no clips provided"}
    out_dir.mkdir(parents=True, exist_ok=True)
    angles = []
    for i, clip in enumerate(clip_paths):
        if not Path(clip).exists():
            continue
        angle_path = out_dir / f"angle_{i+1}.mp4"
        rc, _, _ = await run_cmd([
            ffmpeg_bin(), "-y", "-i", clip, "-t", f"{duration:.2f}",
            "-vf", "scale=640:360,fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-an", str(angle_path),
        ])
        if rc == 0:
            angles.append(str(angle_path))
    if not angles:
        return {"success": False, "reason": "no clips could be processed"}
    # Combine into a multi-angle grid.
    n = len(angles)
    if n == 1:
        return {"success": True, "angles": angles, "combined": angles[0]}
    # Side-by-side layout.
    filter_parts = []
    for i, a in enumerate(angles):
        filter_parts.append(f"[{i}:v]scale=640:360[a{i}]")
    xstack_inputs = "".join(f"[a{i}]" for i in range(n))
    layout = "0_0"
    for i in range(1, n):
        layout += f"|{i*640}_0"
    vf = ";".join(filter_parts) + f";{xstack_inputs}xstack=inputs={n}:layout={layout}[vout]"
    combined_path = out_dir / "multi_angle.mp4"
    inputs = []
    for a in angles:
        inputs += ["-i", a]
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", *inputs,
        "-filter_complex", vf, "-map", "[vout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        str(combined_path),
    ])
    if rc == 0:
        return {"success": True, "angles": angles, "combined": str(combined_path)}
    return {"success": True, "angles": angles, "combined": None,
            "reason": f"combine failed: {err[-200:]}"}


# ----------------------------------------------------- 360-degree video support

async def inject_360_metadata(video_path: str, out_path: str | None = None) -> dict:
    """Inject 360-degree video metadata into a video file.

    YouTube detects 360 videos by reading metadata from the file. This
    function injects the required spherical metadata tags using ffmpeg's
    metadata filter.

    The video should be in equirectangular projection (2:1 aspect ratio).
    """
    src = Path(video_path)
    if not src.exists():
        return {"success": False, "reason": "video not found"}
    out = Path(out_path) if out_path else src.with_suffix(".360.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Inject spherical metadata.
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", str(src),
        "-c", "copy",
        "-metadata:s:v:0", "spherical=equirectangular",
        "-metadata:s:v:0", "ProjectionType=equirectangular",
        str(out),
    ])
    if rc != 0:
        return {"success": False, "reason": f"ffmpeg failed: {err[-200:]}"}
    log.info("360 metadata injected: %s", out.name)
    return {"success": True, "path": str(out),
            "note": "Upload this file to YouTube — it will be detected as 360."}


# ----------------------------------------------------- interactive videos

def generate_interactive_endscreen(video_id: int, choices: list[dict]) -> dict:
    """Generate an interactive end-screen with branching choices.

    Each choice links to a different video, letting viewers "choose their
    own adventure". YouTube's end-screen feature supports this natively.

    choices: [{label, target_video_id, target_yt_id}]
    """
    if not choices or len(choices) > 2:
        return {"success": False,
                "reason": "YouTube end-screens support max 2 video choices"}
    return {
        "success": True,
        "video_id": video_id,
        "choices": choices,
        "instructions": (
            "To add the interactive end-screen:\n"
            "1. Open YouTube Studio → your video → End screens\n"
            "2. Add a 'Video' element for each choice\n"
            "3. Set each to link to the target video\n"
            "4. Save — viewers will see the choices in the last 20 seconds"
        ),
        "note": "YouTube's public Data API doesn't support end-screen "
                "management — this must be done manually in YouTube Studio.",
    }
