#!/usr/bin/env python3
"""Safe section-quality checks for long, Shorts, AI Story, and special uploads."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings
from app.database import session_scope
from app.models import Video
from app.services import ai_story, auto_upload, scriptwriter, shorts_clipper
from app.core.utils import probe_duration


async def main() -> None:
    original = {
        "youtube_dry_run": settings.youtube_dry_run,
        "force_mock_youtube": settings.force_mock_youtube,
        "force_mock_llm": settings.force_mock_llm,
        "approval_required": settings.approval_required,
    }
    settings.force_mock_llm = True

    # The deterministic fallback must scale its spoken word budget with target length.
    short_script = await scriptwriter.write_script("ocean mysteries", "science", target_seconds=60)
    long_script = await scriptwriter.write_script("ocean mysteries", "science", target_seconds=300)
    short_words = sum(len(s["narration"].split()) for s in short_script["scenes"])
    long_words = sum(len(s["narration"].split()) for s in long_script["scenes"])
    assert long_words > short_words * 3, (short_words, long_words)
    print(json.dumps({"script_duration_scaling": True, "short_words": short_words, "long_words": long_words}))

    # Unknown story languages must fall back safely instead of raising a NameError.
    story = await ai_story.generate_story("a brave fox", language="xx", scene_count=3, target_seconds=30)
    assert story.get("scenes") and story.get("language") == "xx"
    assert sum(len(s["narration"].split()) for s in story["scenes"]) >= 60
    print(json.dumps({"ai_story_unknown_language_fallback": True, "scenes": len(story["scenes"]), "words": sum(len(s["narration"].split()) for s in story["scenes"])}))

    # Assemble a real story MP4 with deterministic local image/audio providers.
    import subprocess
    async def fake_image(prompt: str, out_path: Path, seed: int | None = None) -> bool:
        return await ai_story.generate_fallback_image(prompt, out_path)
    async def fake_synthesize(text: str, out_path: Path, language: str, index: int) -> dict:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3.2",
            "-c:a", "libmp3lame", "-q:a", "5", str(out_path),
        ], capture_output=True, check=True)
        return {"path": str(out_path), "duration": 3.2, "words": text.split(), "engine": "test"}
    old_image, old_synthesize = ai_story.generate_scene_image, ai_story.synthesize
    ai_story.generate_scene_image, ai_story.synthesize = fake_image, fake_synthesize
    story_for_render = {
        "title": "A Brave Fox", "genre": "animal_tale", "language": "en",
        "target_seconds": 10, "scenes": [
            {"index": 0, "narration": "A brave fox finds a safe path.", "image_prompt": "fox in a bright forest"},
            {"index": 1, "narration": "The fox helps a friend cross the river.", "image_prompt": "fox beside a river"},
        ],
    }
    story_render = await ai_story.assemble_story_video(story_for_render, 9901, "en")
    ai_story.generate_scene_image, ai_story.synthesize = old_image, old_synthesize
    assert story_render.get("success") and Path(story_render["path"]).exists()
    story_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,codec_name",
         "-of", "json", story_render["path"]], capture_output=True, text=True, check=True)
    story_info = json.loads(story_probe.stdout)
    story_video = next(s for s in story_info["streams"] if s["codec_type"] == "video")
    story_audio = next(s for s in story_info["streams"] if s["codec_type"] == "audio")
    assert (story_video["width"], story_video["height"]) == (1920, 1080)
    assert story_audio["codec_name"] == "aac"
    print(json.dumps({"ai_story_mp4": True, "resolution": [story_video["width"], story_video["height"]], "audio": story_audio["codec_name"], "path": story_render["path"]}))

    # Metadata fallback must work for an unknown video type.
    metadata = await auto_upload.generate_metadata("a funny cartoon moment", "entertainment", video_type="unknown")
    assert metadata.get("title") and isinstance(metadata.get("tags"), list)
    print(json.dumps({"metadata_fallback": True, "title": metadata["title"][:60]}))

    # Produce a real 9:16 MP4 from an existing rendered video.
    parent = Path(settings.path(settings.data_dir, "output", "v8_final.mp4"))
    assert parent.exists(), parent
    out = Path("/tmp/phoenix_quality_audit_short.mp4")
    clip = await shorts_clipper.clip_short(parent, out, 1.0, 16.0)
    assert out.exists() and out.stat().st_size > 50_000
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,codec_name",
         "-of", "json", str(out)], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    video_stream = next(s for s in streams if s["codec_type"] == "video")
    audio_stream = next(s for s in streams if s["codec_type"] == "audio")
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
    assert audio_stream["codec_name"] == "aac"
    print(json.dumps({"short_mp4": clip, "resolution": [video_stream["width"], video_stream["height"]], "audio": audio_stream["codec_name"]}))

    # Special-flow auto upload must stop at review in live mode.
    settings.youtube_dry_run = False
    settings.force_mock_youtube = False
    settings.approval_required = True
    result = await auto_upload.auto_upload_video(
        str(parent), channel_id=1, topic="Safety gate test", niche="entertainment",
        is_short=True, auto_publish=True)
    assert result.get("awaiting_review") is True, result
    test_id = result.get("video_id")
    with session_scope() as db:
        row = db.get(Video, test_id)
        assert row and row.status == "awaiting_review" and row.review_status == "pending"
        db.delete(row)
    print(json.dumps({"special_flow_approval_gate": True}))

    settings.youtube_dry_run = original["youtube_dry_run"]
    settings.force_mock_youtube = original["force_mock_youtube"]
    settings.force_mock_llm = original["force_mock_llm"]
    settings.approval_required = original["approval_required"]
    out.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
