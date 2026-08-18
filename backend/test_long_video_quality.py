"""Focused regression checks for long-form duration and Urdu narration quality."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings
from app.services import editor, scriptwriter, voice
from app.core.utils import probe_duration


async def main() -> None:
    settings.force_mock_llm = True
    target = 30
    script = await scriptwriter.write_script(
        "pani bachane ke asan tareeqe", "education", language="ur",
        target_seconds=target, content_type="tutorial",
    )
    words = sum(len(scene["narration"].split()) for scene in script["scenes"])
    assert script.get("purpose")
    assert script.get("takeaways")
    assert words >= int(target * 1.5), words
    assert voice.pick_voice("ur") == "ur-PK-AsadNeural"
    normalized = voice._normalize_urdu_text("یہی لفظي ختم ي، ایک لمبا جملہ ہے، جسے صاف وقفوں کے ساتھ پڑھنا چاہیے۔")
    assert "ے" in normalized and "ي" not in normalized

    root = Path(settings.path(settings.data_dir, "output", "long_quality_test"))
    root.mkdir(parents=True, exist_ok=True)
    scenes = []
    for i in range(3):
        clip = root / f"clip_{i}.mp4"
        wav = root / f"voice_{i}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x22152f:s=640x360:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(clip),
        ], capture_output=True, check=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=9.55",
            "-ar", "44100", "-ac", "2", str(wav),
        ], capture_output=True, check=True)
        scenes.append({
            "clip_path": str(clip), "voice_path": str(wav), "voice_duration": 9.55,
            "narration": script["scenes"][i % len(script["scenes"])] ["narration"],
            "emphasis": [], "words": [],
        })

    out = root / "final.mp4"
    result = await editor.render_video(
        9902, scenes, None, out, (640, 360),
        show_captions=False, cinematic=False,
    )
    measured = await probe_duration(str(out))
    assert measured > 0
    assert abs(float(result["duration"]) - measured) < 0.2
    assert abs(measured - 30.0) <= 1.0, measured
    print(json.dumps({
        "long_duration_verification": True,
        "requested_seconds": target,
        "measured_seconds": round(measured, 2),
        "urdu_voice": voice.pick_voice("ur"),
        "script_words": words,
        "purpose_present": bool(script.get("purpose")),
    }))


if __name__ == "__main__":
    asyncio.run(main())
