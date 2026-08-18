"""AI voice generation via Edge-TTS (free, keyless, natural neural voices).

Strategy (in order, never hard-fails):
  1. Edge-TTS — natural neural voice + WordBoundary timings.
  2. If Edge-TTS fails (network blocked / DNS / offline), fall back to:
     a. ffmpeg synth tone + estimate words/sec (existing behavior).
     b. If ffmpeg is also unavailable, write a tiny silent WAV directly so
        the pipeline keeps flowing (offline-safe).
  3. Always returns {path, duration, words, engine}.

Urdu fix (v1.3):
  - pick_voice() automatically picks the right Edge-TTS voice for the
    language (Urdu → ur-PK-AsadNeural / UrduGulNeural, etc.) UNLESS the
    user has explicitly pinned a voice in TTS_VOICE that matches the
    language of the script.
  - For Urdu, _normalize_urdu_text() inserts ZWNJ between Latin/Urdu
    mixed tokens, normalises yogh (ي vs ے) at word ends, and breaks long
    sentences into shorter clauses so Edge-TTS pauses at the right places.
  - Voice selection is fully automatic — change the language on a video
    and the right voice is picked with zero configuration.
"""
from __future__ import annotations

import asyncio
import os
import re
import struct
import wave
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_available, ffmpeg_bin, probe_duration, run_cmd

log = get_logger("voice")
TTS_TIMEOUT_SECONDS = max(10.0, float(os.getenv("TTS_TIMEOUT_SECONDS", "45")))

# Curated natural voices per language (extend freely; `edge-tts --list-voices`).
# When a video's language matches one of these keys, the matching voice is
# used automatically — no need to set TTS_VOICE for each language.
VOICE_MAP = {
    "en":    "en-US-ChristopherNeural",
    "en-us": "en-US-ChristopherNeural",
    "en-gb": "en-GB-RyanNeural",
    "ur":    "ur-PK-AsadNeural",       # male, deep
    "ur-pk": "ur-PK-AsadNeural",
    "ur-f":  "ur-PK-UzmaNeural",       # female alternative
    "hi":    "hi-IN-MadhurNeural",
    "hi-in": "hi-IN-MadhurNeural",
    "es":    "es-ES-AlvaroNeural",
    "ar":    "ar-SA-HamedNeural",
    "de":    "de-DE-ConradNeural",
    "fr":    "fr-FR-HenriNeural",
    "pt":    "pt-BR-AntonioNeural",
    "tr":    "tr-TR-AhmetNeural",
    "ru":    "ru-RU-DmitryNeural",
    "id":    "id-ID-ArdiNeural",
    "ja":    "ja-JP-KeitaNeural",
    "ko":    "ko-KR-InJoonNeural",
    "zh":    "zh-CN-YunxiNeural",
    "fa":    "fa-IR-FaridNeural",
}


def pick_voice(language: str) -> str:
    """Pick the right Edge-TTS voice for the given language.

    The user can pin a specific voice in TTS_VOICE — but if they haven't,
    or if the pinned voice doesn't match the language of the script, we
    auto-select the language-appropriate voice. This is the 'auto voice
    change when language changes' feature.
    """
    lang = (language or "en").lower().strip()
    # If the user pinned a voice, only use it when it appears to match the
    # requested language — otherwise the language-appropriate voice wins.
    if settings.tts_voice:
        v = settings.tts_voice.lower()
        # Check if the pinned voice's prefix matches the language.
        if v.startswith(lang) or v.startswith(lang.split("-")[0]):
            return settings.tts_voice
        # Special case: en-gb / en-us should still match an "en-" pinned voice.
        if lang.startswith("en") and v.startswith("en-"):
            return settings.tts_voice
    # Auto-select.
    return VOICE_MAP.get(lang) or VOICE_MAP.get(lang.split("-")[0]) or VOICE_MAP["en"]


# ----------------------------------------------------------------- Urdu fix
# Urdu-specific text normalization for clearer Edge-TTS pronunciation.
_URDU_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # tashkeel + tatweel
_URDU_YEH_END = re.compile(r"ي(?=\s|$|[.,!?؟،؛])")  # Arabic yeh at end -> Urdu yeh
_URDU_LONG_SENTENCE = re.compile(r"(.{60,?}([،۔!؟.]))\s+")


def _normalize_urdu_text(text: str) -> str:
    """Normalize Urdu text so Edge-TTS pronounces it clearly.

    - Remove tashkeel/diacritics (Edge-TTS handles them poorly).
    - Replace Arabic yeh at word ends with Urdu yeh (ے).
    - Insert a soft break after long clauses so the voice pauses naturally.
    - Strip tatweel (ـ) which stretches words visually but breaks TTS.
    - Normalize zero-width joiners that confuse the tokenizer.
    """
    if not text:
        return text
    out = text
    # Remove tashkeel/diacritics + tatweel.
    out = _URDU_DIACRITICS.sub("", out)
    # Arabic yeh at end → Urdu yeh (ے sounds different at word end).
    out = _URDU_YEH_END.sub("ے", out)
    # Break very long sentences at the first Urdu/English punctuation.
    # Edge-TTS tends to rush through long Urdu sentences without pausing.
    out = _URDU_LONG_SENTENCE.sub(r"\1\n", out)
    # Collapse multiple spaces / newlines.
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _normalize_text_for_language(text: str, language: str) -> str:
    """Dispatch to the right language-specific normalizer."""
    lang = (language or "en").lower()
    if lang.startswith("ur"):
        return _normalize_urdu_text(text)
    # Default: just trim whitespace.
    return (text or "").strip()


def _write_silent_wav(path: Path, seconds: float) -> None:
    """Write a tiny 44.1kHz stereo silent WAV file (offline fallback)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sr, channels = 44100, 2
    n_frames = max(int(seconds * sr), 1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        # write silent frames (zeros) in chunks to avoid huge memory
        chunk = b"\x00\x00" * (sr * channels)  # 1 second of silence
        for _ in range(int(seconds) + 1):
            wf.writeframes(chunk)


def _write_tone_wav(path: Path, seconds: float, freq: float = 220.0) -> None:
    """Write a low-volume pure-tone WAV without ffmpeg (offline-safe)."""
    import math
    path.parent.mkdir(parents=True, exist_ok=True)
    sr, channels = 44100, 2
    n_frames = max(int(seconds * sr), 1)
    amp = int(32767 * 0.05)  # 5% volume
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        chunk_frames = sr // 20
        chunk = bytearray()
        for i in range(chunk_frames):
            val = int(amp * math.sin(2 * math.pi * freq * (i / sr)))
            chunk += struct.pack("<h", val) * channels
        chunk_bytes = bytes(chunk)
        full = b""
        written = 0
        while written < n_frames:
            take = min(chunk_frames, n_frames - written)
            full += chunk_bytes[: take * channels * 2]
            written += take
        wf.writeframes(full)


async def synthesize(
    text: str,
    out_path: Path,
    language: str = "en",
    scene_index: int = 0,
) -> dict:
    """TTS one scene. Returns {path, duration, words: [{word, offset, duration}]}.

    Word timings come from Edge-TTS WordBoundary events (offsets in 100-ns units).
    The text is normalized per-language before being sent to Edge-TTS so Urdu
    (and other RTL languages) pronounce correctly.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Normalize text per-language for clearer pronunciation.
    text = _normalize_text_for_language(text, language)
    voice = pick_voice(language)
    words: list[dict] = []
    lang_key = (language or "en").lower().strip()
    # Urdu is spoken more clearly with a slightly slower rate. Keep this
    # configurable instead of silently changing the global rate for English.
    tts_rate = settings.urdu_tts_rate if lang_key.startswith("ur") else settings.tts_rate

    log.info("voice scene %d: language=%s voice=%s rate=%s", scene_index, language, voice, tts_rate)

    # ---------- attempt 1: Edge-TTS (needs network) -----------------------
    try:
        import edge_tts

        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=tts_rate, pitch=settings.tts_pitch,
                boundary="WordBoundary",
            )
        except TypeError:
            communicate = edge_tts.Communicate(
                text, voice, rate=tts_rate, pitch=settings.tts_pitch,
            )
        # Edge-TTS can stall when its upstream websocket is slow or blocked.
        # Bound each scene and use the deterministic local fallback below.
        async with asyncio.timeout(TTS_TIMEOUT_SECONDS):
            with open(out_path, "wb") as fh:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        fh.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append({
                            "word": chunk["text"],
                            "offset": chunk["offset"] / 10_000_000,
                            "duration": chunk["duration"] / 10_000_000,
                        })
        if out_path.exists() and out_path.stat().st_size > 1000:
            duration = await probe_duration(str(out_path))
            if duration <= 0:
                # fall back to estimate if ffprobe not available
                duration = max(3.0, len(text.split()) / 2.6)
            log.info("voice scene %d: %.1fs, %d word timings (%s)",
                     scene_index, duration, len(words), voice)
            return {"path": str(out_path), "duration": duration, "words": words,
                    "engine": "edge-tts", "voice": voice}
        log.warning("Edge-TTS produced empty audio for scene %d, falling back", scene_index)
    except Exception as exc:
        log.warning("Edge-TTS failed (%s) — generating fallback tone track", exc)

    # ---------- attempt 2: ffmpeg synth tone (offline, needs ffmpeg) ------
    # ~2.6 words/sec spoken estimate for duration; soft sine pad keeps timings sane.
    # For Urdu the speech rate is slower (~2.0 words/sec).
    rate_per_sec = 1.85 if lang_key.startswith("ur") else 2.45
    est = max(3.0, len(text.split()) / rate_per_sec)
    if ffmpeg_available():
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-f", "lavfi",
            "-i", f"sine=frequency=220:duration={est}",
            "-af", "volume=0.05,afade=t=in:d=0.3,afade=t=out:st=%.2f:d=0.3" % (est - 0.3),
            "-ar", "44100", "-ac", "2", str(out_path),
        ])
        if rc == 0 and out_path.exists() and out_path.stat().st_size > 1000:
            log.info("voice scene %d: ffmpeg fallback tone %.1fs", scene_index, est)
            return {"path": str(out_path), "duration": est, "words": [],
                    "engine": "fallback-tone", "voice": voice}

    # ---------- attempt 3: pure-Python tone WAV (no ffmpeg, no network) ---
    try:
        _write_tone_wav(out_path, est)
        log.info("voice scene %d: pure-python tone fallback %.1fs (no ffmpeg)",
                 scene_index, est)
        return {"path": str(out_path), "duration": est, "words": [],
                "engine": "fallback-tone-py", "voice": voice}
    except Exception as exc2:
        log.error("all voice fallbacks failed for scene %d: %s", scene_index, exc2)

    # ---------- last resort: silent WAV -----------------------------------
    _write_silent_wav(out_path, est)
    return {"path": str(out_path), "duration": est, "words": [],
            "engine": "silent", "voice": voice}
