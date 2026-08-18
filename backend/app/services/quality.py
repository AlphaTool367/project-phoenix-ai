"""Automatic quality checks for rendered videos.

The checks are intentionally artifact-based: they inspect the final file rather
than trusting a planned scene count or an estimated duration.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffprobe_bin, probe_duration, run_cmd

log = get_logger("quality")


async def inspect_rendered_video(
    path: str | Path,
    target_seconds: float,
    script: dict | None = None,
) -> dict:
    """Inspect the final MP4 and return a persisted quality report."""
    p = Path(path)
    report: dict = {
        "path": str(p),
        "exists": p.exists(),
        "file_size_bytes": p.stat().st_size if p.exists() else 0,
        "target_seconds": float(target_seconds),
        "measured_seconds": 0.0,
        "duration_delta_seconds": None,
        "duration_tolerance_seconds": 0.0,
        "duration_ok": False,
        "has_video": False,
        "has_audio": False,
        "purpose_present": bool((script or {}).get("purpose")),
        "takeaways_present": bool((script or {}).get("takeaways")),
        "script_words": sum(len(str(s.get("narration", "")).split())
                            for s in (script or {}).get("scenes", [])),
        "critical_errors": [],
        "warnings": [],
        "quality_score": 0,
    }
    if not p.exists() or p.stat().st_size < 100_000:
        report["critical_errors"].append("final video file is missing or unexpectedly small")
        return report

    measured = await probe_duration(str(p))
    report["measured_seconds"] = round(float(measured or 0.0), 3)
    report["duration_delta_seconds"] = round(
        abs(report["measured_seconds"] - float(target_seconds)), 3
    )
    tolerance = max(
        float(settings.duration_tolerance_seconds),
        abs(float(target_seconds)) * float(settings.duration_tolerance_ratio),
    )
    report["duration_tolerance_seconds"] = round(tolerance, 3)
    report["duration_ok"] = bool(
        report["measured_seconds"] > 0
        and report["duration_delta_seconds"] <= tolerance
    )
    if not report["duration_ok"]:
        report["critical_errors"].append(
            f"duration outside tolerance: requested {target_seconds:.1f}s, "
            f"measured {report['measured_seconds']:.1f}s, allowed ±{tolerance:.1f}s"
        )

    try:
        rc, stdout, stderr = await run_cmd([
            ffprobe_bin(), "-v", "error", "-show_entries",
            "stream=codec_type,codec_name", "-of", "json", str(p),
        ])
        if rc != 0:
            report["critical_errors"].append(f"ffprobe stream inspection failed: {stderr[-300:]}")
        else:
            streams = json.loads(stdout or "{}").get("streams", [])
            types = {s.get("codec_type") for s in streams}
            report["has_video"] = "video" in types
            report["has_audio"] = "audio" in types
    except Exception as exc:
        report["critical_errors"].append(f"media stream inspection failed: {exc}")

    if not report["has_video"]:
        report["critical_errors"].append("final file has no video stream")
    if not report["has_audio"]:
        report["critical_errors"].append("final file has no audio stream")
    if not report["purpose_present"]:
        report["warnings"].append("script purpose metadata is missing")
    if not report["takeaways_present"]:
        report["warnings"].append("script takeaways metadata is missing")
    if report["script_words"] < max(20, int(float(target_seconds) * 0.5)):
        report["warnings"].append("script word budget may be too short for the requested duration")

    score = 0
    score += 35 if report["duration_ok"] else 0
    score += 25 if report["has_video"] and report["has_audio"] else 0
    score += 15 if report["file_size_bytes"] >= 100_000 else 0
    score += 15 if report["purpose_present"] else 0
    score += 10 if report["script_words"] >= max(20, int(float(target_seconds) * 0.5)) else 0
    report["quality_score"] = score
    report["passed"] = not report["critical_errors"]
    return report
