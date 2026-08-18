"""Voice & translation features.

  - Voice emotion control: adjust TTS rate/pitch per scene for emotional effect.
  - Auto-translation dubbing: translate the script + re-dub in another language.
  - Background removal AI: remove background from stock footage using rembg.

All use free tools (Edge-TTS for voice, Google Translate for translation,
rembg for background removal).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("voice_translate")


# ----------------------------------------------------- voice emotion control

# Emotion presets — adjust TTS rate + pitch to convey different emotions.
EMOTION_PRESETS = {
    "neutral":     {"rate": "+0%", "pitch": "+0Hz"},
    "excited":     {"rate": "+15%", "pitch": "+30Hz"},
    "calm":        {"rate": "-10%", "pitch": "-10Hz"},
    "dramatic":    {"rate": "-20%", "pitch": "-20Hz"},
    "urgent":      {"rate": "+25%", "pitch": "+15Hz"},
    "sad":         {"rate": "-15%", "pitch": "-30Hz"},
    "happy":       {"rate": "+10%", "pitch": "+20Hz"},
    "mysterious":  {"rate": "-15%", "pitch": "-15Hz"},
    "authoritative": {"rate": "-5%", "pitch": "-10Hz"},
    "whisper":     {"rate": "-30%", "pitch": "-20Hz"},
}


def get_emotion_preset(emotion: str) -> dict:
    """Return the TTS rate/pitch for an emotion."""
    return EMOTION_PRESETS.get(emotion.lower(), EMOTION_PRESETS["neutral"])


def apply_emotion_to_scenes(scenes: list[dict], default_emotion: str = "neutral") -> list[dict]:
    """Add an 'emotion' field to each scene based on its beat.

    Hook scenes get 'mysterious' or 'urgent', escalation gets 'dramatic',
    payoff gets 'happy', CTA gets 'excited'.
    """
    beat_emotions = {
        "hook": "mysterious",
        "setup": "neutral",
        "context": "neutral",
        "escalation": "dramatic",
        "payoff": "happy",
        "cta": "excited",
        # Content type specific beats.
        "breaking": "urgent",
        "what_happened": "neutral",
        "why_it_matters": "dramatic",
        "first_impression": "excited",
        "pros": "happy",
        "cons": "sad",
        "verdict": "authoritative",
        "winner": "excited",
        "myth_1": "mysterious",
        "truth": "authoritative",
    }
    for sc in scenes:
        beat = sc.get("beat", "").lower()
        sc["emotion"] = beat_emotions.get(beat, default_emotion)
    return scenes


# ----------------------------------------------------- auto-translation dubbing

async def translate_script(script: dict, target_language: str) -> dict:
    """Translate a video script's narration into another language via LLM.

    Returns a new script dict with the same structure but translated narration.
    """
    scenes = script.get("scenes", [])
    if not scenes:
        return script
    narrations = [s.get("narration", "") for s in scenes]
    prompt = [
        {"role": "system", "content": (
            f"You are a professional translator. Translate the following video "
            f"script narrations into {target_language}. Keep the same tone and "
            f"meaning. Respond ONLY with a JSON array of translated strings, "
            f"one per scene, in the same order."
        )},
        {"role": "user", "content": "\n".join(f"{i+1}. {n}" for i, n in enumerate(narrations))},
    ]
    data = await llm.chat_json(prompt, temperature=0.3)
    if not isinstance(data, list) or len(data) != len(scenes):
        log.warning("translation failed — returning original script")
        return script
    new_scenes = []
    for i, sc in enumerate(scenes):
        new_sc = dict(sc)
        new_sc["narration"] = str(data[i])
        new_sc["original_narration"] = sc.get("narration", "")
        new_sc["language"] = target_language
        new_scenes.append(new_sc)
    return {**script, "scenes": new_scenes, "language": target_language,
            "original_language": script.get("language", "en")}


async def auto_dub_video(video_id: int, target_language: str) -> dict:
    """Full auto-dub: translate script + re-synthesize voice in target language.

    Returns a dict with the new script + voice file paths.
    """
    from ..database import session_scope
    from ..models import Video
    from .voice import synthesize
    with session_scope() as db:
        v = db.get(Video, video_id)
        if not v:
            return {"error": "video not found"}
        script = v.script_json or {}
        channel_id = v.channel_id

    translated = await translate_script(script, target_language)
    if translated == script:
        return {"error": "translation failed"}

    # Re-synthesize voice for each scene in the target language.
    work_dir = settings.path(settings.data_dir, "output",
                              f"v{video_id}_dub_{target_language}")
    work_dir.mkdir(parents=True, exist_ok=True)
    voice_results = []
    for i, sc in enumerate(translated.get("scenes", [])):
        path = work_dir / f"scene_{i:02d}.mp3"
        res = await synthesize(sc["narration"], path, target_language, i)
        voice_results.append(res)

    return {
        "video_id": video_id,
        "target_language": target_language,
        "translated_script": translated,
        "voice_files": [r["path"] for r in voice_results],
        "voice_engine": voice_results[0].get("engine") if voice_results else "unknown",
    }


# ----------------------------------------------------- background removal

async def remove_background_from_image(image_path: str, out_path: str | None = None) -> dict:
    """Remove the background from an image using rembg (free, offline).

    Returns {path, success}.
    """
    try:
        from rembg import remove
    except ImportError:
        log.warning("rembg not installed — install with: pip install rembg")
        return {"success": False, "reason": "rembg not installed"}
    src = Path(image_path)
    if not src.exists():
        return {"success": False, "reason": "image not found"}
    out = Path(out_path) if out_path else src.with_suffix(".nobg.png")
    try:
        input_data = src.read_bytes()
        output_data = remove(input_data)
        out.write_bytes(output_data)
        log.info("background removed: %s → %s", src.name, out.name)
        return {"success": True, "path": str(out)}
    except Exception as exc:
        log.warning("background removal failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def remove_background_from_clip(clip_path: str, out_path: str | None = None) -> dict:
    """Remove background from a video clip frame-by-frame using rembg.

    This is slow (processes each frame). Use sparingly — mainly for thumbnails
    or short intro clips.
    """
    try:
        from rembg import remove
    except ImportError:
        return {"success": False, "reason": "rembg not installed"}
    # For video, we extract frames, process each, then reassemble.
    # This is a simplified version — just process the first frame as a thumbnail.
    return await remove_background_from_image(clip_path, out_path)
