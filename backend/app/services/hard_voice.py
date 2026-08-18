"""Hard features Group 1 — Voice cloning + Lip-sync AI.

  - Voice cloning: Coqui TTS (open source, runs locally, free). Clone a
    voice from a 30-second sample. Falls back to ElevenLabs free tier
    (5K chars/month) when COQUI is not installed.
  - Lip-sync AI: Wav2Lip (open source, GitHub). Syncs an audio track to
    a talking-head video so the lips move in sync with the dub. Requires
    GPU for reasonable speed.
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import run_cmd

log = get_logger("hard_voice")


# ----------------------------------------------------- voice cloning

def coqui_available() -> bool:
    """Check if Coqui TTS is installed."""
    try:
        import TTS  # noqa: F401
        return True
    except ImportError:
        return False


def elevenlabs_available() -> bool:
    """Check if ElevenLabs API key is set (free tier: 5K chars/month)."""
    import os
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


async def clone_voice_coqui(text: str, voice_sample_path: str,
                             out_path: Path) -> dict:
    """Clone a voice using Coqui TTS (local, free, open source).

    Requires: pip install TTS
    + a 30-second WAV sample of the voice to clone.
    """
    if not coqui_available():
        return {"success": False,
                "reason": "Coqui TTS not installed. Run: pip install TTS"}
    try:
        from TTS.api import TTS as CoquiTTS
        # Load the XTTS v2 model (supports zero-shot voice cloning).
        tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
        tts.tts_to_file(
            text=text,
            file_path=str(out_path),
            speaker_wav=voice_sample_path,
            language="en",
        )
        log.info("voice cloned via Coqui: %s", out_path.name)
        return {"success": True, "path": str(out_path), "engine": "coqui"}
    except Exception as exc:
        log.warning("Coqui voice cloning failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def clone_voice_elevenlabs(text: str, voice_id: str,
                                  out_path: Path) -> dict:
    """Clone a voice using ElevenLabs API (free tier: 5K chars/month).

    Requires: ELEVENLABS_API_KEY in .env.
    Get a free key from https://elevenlabs.io/ (5K chars/month free).
    """
    import os
    import httpx
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        return {"success": False,
                "reason": "ELEVENLABS_API_KEY not set. Get a free key from "
                          "https://elevenlabs.io/"}
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key,
                         "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_monolingual_v1",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}},
            )
        if r.status_code != 200:
            return {"success": False,
                    "reason": f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}"}
        out_path.write_bytes(r.content)
        log.info("voice generated via ElevenLabs: %s", out_path.name)
        return {"success": True, "path": str(out_path), "engine": "elevenlabs"}
    except Exception as exc:
        log.warning("ElevenLabs failed: %s", exc)
        return {"success": False, "reason": str(exc)}


# ----------------------------------------------------- lip-sync AI

def wav2lip_available() -> bool:
    """Check if Wav2Lip is available (cloned from GitHub)."""
    import os
    # Wav2Lip is typically cloned into a folder. Check common locations.
    candidates = [
        os.environ.get("WAV2LIP_PATH", ""),
        str(settings.assets_path / "Wav2Lip" / "inference.py"),
        "Wav2Lip/inference.py",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return True
    return False


async def lip_sync_video(video_path: str, audio_path: str,
                          out_path: str | None = None) -> dict:
    """Lip-sync a video to a new audio track using Wav2Lip.

    This is used after auto-dubbing: the dubbed audio is synced to the
    speaker's lips in the original video. Requires a GPU for reasonable
    speed (CPU works but is very slow).

    Wav2Lip repo: https://github.com/Rudrabha/Wav2Lip
    Clone it + download the checkpoint, then set WAV2LIP_PATH in .env.
    """
    import os
    import subprocess
    wav2lip_path = os.environ.get("WAV2LIP_PATH", "")
    if not wav2lip_path or not Path(wav2lip_path).exists():
        return {"success": False,
                "reason": ("Wav2Lip not configured. Clone the repo + download "
                           "the checkpoint:\n"
                           "  git clone https://github.com/Rudrabha/Wav2Lip\n"
                           "  cd Wav2Lip && pip install -r requirements.txt\n"
                           "  # Download checkpoint from the repo's README\n"
                           "  # Set WAV2LIP_PATH=/path/to/Wav2Lip/inference.py in .env")}
    src_video = Path(video_path)
    src_audio = Path(audio_path)
    if not src_video.exists() or not src_audio.exists():
        return {"success": False, "reason": "video or audio file not found"}
    out = Path(out_path) if out_path else src_video.with_suffix(".lipsync.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Run Wav2Lip inference.
        r = subprocess.run(
            ["python", wav2lip_path,
             "--face", str(src_video),
             "--audio", str(src_audio),
             "--outfile", str(out)],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            return {"success": False,
                    "reason": f"Wav2Lip failed: {r.stderr[-300:]}"}
        return {"success": True, "path": str(out), "engine": "wav2lip"}
    except Exception as exc:
        log.warning("lip-sync failed: %s", exc)
        return {"success": False, "reason": str(exc)}
