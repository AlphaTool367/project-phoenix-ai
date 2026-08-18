"""AI Story Video Generator — generate original story videos using free AI.

Uses:
  - LLM (Grok/Gemini/OpenRouter) to write an original children's story.
  - Pollinations AI (https://image.pollinations.ai/) to generate scene
    images — 100% free, no API key needed, no signup.
  - Edge-TTS for voiceover narration.
  - FFmpeg to assemble images + voice + music into a video.

The result is a 1-3 minute story video with:
  - AI-generated illustrations (one per scene)
  - Narrated voiceover
  - Background music
  - Ken Burns effect (slow zoom/pan on each image)
  - Fade transitions between scenes
  - Burned-in captions

This is similar to YouTube Shorts' AI video feature, but uses
completely free tools.

Flow:
  1. User provides a story prompt (or the LLM generates one).
  2. LLM writes a scene-by-scene story (N scenes, each 10-15 seconds).
  3. For each scene, Pollinations AI generates an illustration.
  4. Edge-TTS narrates each scene.
  5. FFmpeg assembles: images + narration + music → video.
  6. Copyright check + upload.
"""
from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path

import httpx

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp, ffmpeg_bin, probe_duration, run_cmd
from . import llm
from .voice import synthesize

log = get_logger("ai_story")


POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=1280&height=720&nologo=true&seed={seed}"
# Pollinations is a shared free service. Keep requests bounded so concurrent
# story/remix jobs do not create a burst and turn temporary 429s into failures.
POLLINATIONS_CONCURRENCY = max(1, int(os.getenv("POLLINATIONS_CONCURRENCY", "1")))
POLLINATIONS_MIN_INTERVAL = max(0.0, float(os.getenv("POLLINATIONS_MIN_INTERVAL", "1.25")))
POLLINATIONS_RETRIES = max(0, int(os.getenv("POLLINATIONS_RETRIES", "3")))
_POLLINATIONS_SEMAPHORE = asyncio.Semaphore(POLLINATIONS_CONCURRENCY)

# Story genres that work well for viral Shorts.
STORY_GENRES = {
    "kids_fairy_tale": "a magical fairy tale for children with a moral lesson",
    "moral_story": "a short moral story that teaches a life lesson",
    "bedtime_story": "a calming bedtime story for young children",
    "adventure": "an exciting adventure story with a hero",
    "animal_tale": "a story where animals are the main characters",
    "fable": "a classic-style fable with talking animals",
    "scifi_short": "a short sci-fi story about the future",
    "mystery": "a short mystery story with a twist ending",
}


async def generate_story(prompt: str, genre: str = "kids_fairy_tale",
                          scene_count: int = 5,
                          target_seconds: int = 60,
                          language: str = "en") -> dict:
    """Generate an original story using the LLM.

    Returns:
      {title, genre, scenes: [{index, narration, image_prompt}], target_seconds}
    """
    genre_desc = STORY_GENRES.get(genre, STORY_GENRES["kids_fairy_tale"])
    lang_guides = {
        "en": "Write in simple, clear English suitable for children.",
        "ur": "اردو میں لکھیں — سادہ بول چال کی اردو، بچوں کے لیے مناسب۔",
        "hi": "हिंदी में लिखें — बच्चों کے لیے उपयुक्त सरल हिंदी۔",
        "es": "Escribe en español sencillo y claro, adecuado para niños.",
        "ar": "اكتب باللغة العربية المبسطة والواضحة المناسبة للأطفال.",
    }
    lang_guide = lang_guides.get(language, lang_guides["en"])

    prompt_msg = [
        {"role": "system", "content": (
            f"You are a children's storyteller. Write {genre_desc}. "
            f"The story must be original (not a known tale). "
            f"Respond ONLY with JSON: "
            f"{{title: str, scenes: [{{index, narration, image_prompt}}]}}. "
            f"Exactly {scene_count} scenes. Each scene's narration should take "
            f"~{target_seconds // scene_count} seconds to read aloud "
            f"({max(10, target_seconds // scene_count * 2)} words per scene). "
            f"image_prompt should be a 5-10 word English description for an "
            f"AI image generator (e.g. 'a brave little rabbit in a magical forest, "
            f"soft watercolor style, children's book illustration'). "
            f"{lang_guide}"
        )},
        {"role": "user", "content": f"Story idea: {prompt}"},
    ]
    data = await llm.chat_json(prompt_msg, temperature=0.85)
    if not isinstance(data, dict) or not data.get("scenes"):
        # Fallback template.
        return _fallback_story(prompt, genre, scene_count, target_seconds, language)
    return _normalize_story_scenes(
        {**data, "genre": genre, "target_seconds": target_seconds,
         "language": language},
        target_seconds, scene_count, language,
    )


def _normalize_story_scenes(story: dict, target_seconds: int,
                            scene_count: int, language: str) -> dict:
    """Keep story narration close to the selected duration budget.

    TTS duration is driven by spoken words, so short fallback/LLM responses used
    to produce a few seconds even when the UI requested 60–300 seconds.
    """
    scenes = list(story.get("scenes") or [])[:scene_count]
    if not scenes:
        return story
    target_words = max(20, min(140, round(target_seconds * 2.2 / len(scenes))))
    continuations = {
        "en": "The moment becomes clearer as the character notices one more detail, makes a careful choice, and learns why patience matters.",
        "ur": "کہانی آگے بڑھتی ہے جب کردار ایک اہم بات سمجھتا ہے، سوچ سمجھ کر فیصلہ کرتا ہے، اور صبر کی قدر سیکھتا ہے۔",
        "hi": "कहानी आगे बढ़ती है जब पात्र एक महत्वपूर्ण बात समझता है, सोचकर निर्णय लेता है और धैर्य का मूल्य सीखता है।",
        "es": "La historia continúa cuando el personaje entiende un detalle, toma una decisión y descubre por qué la paciencia importa.",
        "ar": "تتقدم القصة عندما يلاحظ البطل تفصيلاً مهماً ويتخذ قراراً هادئاً ويتعلم قيمة الصبر.",
    }
    continuation = continuations.get(language, continuations["en"])
    normalized = []
    for i, scene in enumerate(scenes):
        narration = str(scene.get("narration", "")).strip()
        words = narration.split()
        while len(words) < target_words:
            words.extend(continuation.split())
        normalized.append({**scene, "index": i,
                          "narration": " ".join(words[:target_words])})
    return {**story, "scenes": normalized, "target_seconds": target_seconds,
            "language": language}


def _fallback_story(prompt: str, genre: str, scene_count: int,
                     target_seconds: int, language: str) -> dict:
    """Simple fallback story when the LLM is unavailable."""
    scenes = []
    beats = [
        ("Once upon a time, there was a little hero who lived in a quiet village.", "peaceful village illustration, watercolor style"),
        ("One day, something unexpected happened that changed everything.", "dramatic moment, bright colors, storybook style"),
        ("The hero embarked on a journey to find the answer.", "hero on a journey, fantasy landscape, soft illustration"),
        ("Along the way, they met a wise friend who helped them.", "two friends in a magical forest, warm lighting"),
        ("In the end, the hero learned an important lesson about courage.", "hero victorious, golden sunset, children's book art"),
        ("And they all lived happily ever after.", "happy ending celebration, warm colors, storybook illustration"),
    ]
    for i in range(scene_count):
        beat, img = beats[min(i, len(beats) - 1)]
        scenes.append({"index": i, "narration": beat, "image_prompt": img})
    return _normalize_story_scenes({
        "title": f"The Story of {prompt[:30]}", "genre": genre,
        "scenes": scenes, "target_seconds": target_seconds,
        "language": language, "engine": "fallback",
    }, target_seconds, scene_count, language)


async def generate_scene_image(image_prompt: str, out_path: Path,
                                seed: int | None = None) -> bool:
    """Generate a scene image using Pollinations AI (free, no key needed).

    Pollinations generates images from text prompts via a simple URL:
      https://image.pollinations.ai/prompt/{prompt}

    No API key, no signup, no rate limit (be reasonable).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if seed is None:
        seed = random.randint(1, 1_000_000)
    url = POLLINATIONS_URL.format(
        prompt=httpx.URL("https://image.pollinations.ai/prompt/" + image_prompt).path.lstrip("/"),
        seed=seed,
    )
    # Simplified URL construction.
    from urllib.parse import quote_plus
    url = f"https://image.pollinations.ai/prompt/{quote_plus(image_prompt)}?width=1280&height=720&nologo=true&seed={seed}"
    async with _POLLINATIONS_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                for attempt in range(POLLINATIONS_RETRIES + 1):
                    if attempt:
                        # Exponential backoff for transient throttling. The
                        # previous response's Retry-After is honoured below.
                        await asyncio.sleep(min(20.0, 2.0 ** attempt))
                    try:
                        r = await client.get(url)
                    except Exception as exc:
                        if attempt >= POLLINATIONS_RETRIES:
                            log.warning("Pollinations request failed after %d retries: %s", attempt, exc)
                            return False
                        log.warning("Pollinations request retry %d/%d: %s", attempt + 1, POLLINATIONS_RETRIES, exc)
                        continue

                    if r.status_code == 200:
                        if len(r.content) < 5000:
                            log.warning("Pollinations returned tiny image (%d bytes)", len(r.content))
                            return False
                        out_path.write_bytes(r.content)
                        log.info("generated scene image: %s (seed=%d)", out_path.name, seed)
                        await asyncio.sleep(POLLINATIONS_MIN_INTERVAL)
                        return True

                    if r.status_code == 429 and attempt < POLLINATIONS_RETRIES:
                        retry_after = r.headers.get("retry-after")
                        try:
                            wait = max(2.0, min(20.0, float(retry_after))) if retry_after else min(20.0, 2.0 ** (attempt + 1))
                        except ValueError:
                            wait = min(20.0, 2.0 ** (attempt + 1))
                        log.warning("Pollinations returned 429; retrying in %.1fs (%d/%d)", wait, attempt + 1, POLLINATIONS_RETRIES)
                        await asyncio.sleep(wait)
                        continue

                    log.warning("Pollinations returned %d for: %s", r.status_code, image_prompt[:50])
                    return False
        except Exception as exc:
            log.warning("Pollinations image generation failed: %s", exc)
            return False


async def generate_fallback_image(image_prompt: str, out_path: Path) -> bool:
    """Generate a colored gradient image as fallback when Pollinations fails."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import hashlib
        import numpy as np
        w, h = 1280, 720
        # Generate a gradient based on the prompt hash.
        seed = int(hashlib.md5(image_prompt.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        c1 = (rng.randint(50, 255), rng.randint(50, 255), rng.randint(50, 255))
        c2 = (rng.randint(0, 100), rng.randint(0, 100), rng.randint(0, 100))
        t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        grad = (np.array(c1, dtype=np.float32) * (1 - t) + np.array(c2, dtype=np.float32) * t)
        img = Image.fromarray(np.broadcast_to(grad, (h, w, 3)).astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        # Add the prompt text as overlay.
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        except Exception:
            font = ImageFont.load_default()
        # Wrap text.
        import textwrap
        lines = textwrap.wrap(image_prompt, width=40)[:3]
        y = h // 2 - len(lines) * 30
        for line in lines:
            d.text((50, y), line, font=font, fill=(255, 255, 255),
                   stroke_width=3, stroke_fill=(0, 0, 0))
            y += 60
        img.save(out_path, quality=92)
        return True
    except Exception as exc:
        log.warning("fallback image failed: %s", exc)
        return False


async def assemble_story_video(story: dict, video_id: int,
                                voice_language: str = "en",
                                music_path: str | None = None) -> dict:
    """Assemble the final story video from scenes.

    For each scene:
      1. Generate AI image (Pollinations).
      2. Generate voiceover (Edge-TTS).
      3. Apply Ken Burns effect (slow zoom).

    Then concatenate all scenes + add music + captions.
    """
    work = settings.path(settings.data_dir, "output", f"story_v{video_id}_work")
    work.mkdir(parents=True, exist_ok=True)

    scenes = story.get("scenes", [])
    if not scenes:
        return {"success": False, "reason": "no scenes in story"}

    # Generate images + voice in parallel.
    async def process_scene(i: int, scene: dict) -> dict:
        img_path = work / f"scene_{i:02d}.png"
        voice_path = work / f"voice_{i:02d}.mp3"

        # Image (try Pollinations, fallback to gradient).
        img_ok = await generate_scene_image(
            scene.get("image_prompt", "fantasy landscape"), img_path)
        if not img_ok:
            img_ok = await generate_fallback_image(
                scene.get("image_prompt", "fantasy landscape"), img_path)
        if not img_ok or not img_path.exists() or img_path.stat().st_size < 1000:
            return {"index": i, "clip_path": "", "voice_path": "",
                    "duration": 0.0, "reason": "scene image generation failed"}

        # Voice.
        narration = scene.get("narration", "")
        voice_result = await synthesize(narration, voice_path, voice_language, i)
        duration = float(voice_result.get("duration", 10.0) or 10.0)
        if not voice_path.exists() or voice_path.stat().st_size < 1000:
            return {"index": i, "clip_path": "", "voice_path": "",
                    "duration": 0.0, "reason": "voice synthesis produced no audio"}

        # Ken Burns effect: create a video clip from the image with slow zoom.
        clip_path = work / f"clip_{i:02d}.mp4"
        zoom_dur = max(duration, 3.0)
        frames = int(zoom_dur * 30)
        vf = (f"scale=1920:1080:force_original_aspect_ratio=decrease,"
              f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
              f"zoompan=z='min(zoom+0.0008,1.25)':d={frames}:s=1920x1080:fps=30,"
              f"format=yuv420p,fade=t=in:st=0:d=0.5,fade=t=out:st={max(zoom_dur-0.5,0):.2f}:d=0.5")
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-loop", "1", "-i", str(img_path),
            "-i", str(voice_path),
            "-vf", vf, "-t", f"{zoom_dur:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            str(clip_path),
        ])
        if rc != 0:
            log.warning("scene %d clip failed: %s", i, err[-200:])
            return {"index": i, "clip_path": "", "voice_path": str(voice_path),
                    "duration": duration}
        return {"index": i, "clip_path": str(clip_path),
                "voice_path": str(voice_path), "duration": duration}

    # Process all scenes.
    scene_results = await asyncio.gather(*[
        process_scene(i, sc) for i, sc in enumerate(scenes)
    ])

    # Concatenate all clips.
    valid_clips = [r for r in scene_results if r.get("clip_path")]
    if not valid_clips:
        return {"success": False, "reason": "no valid clips generated"}

    concat_file = work / "concat.txt"
    # FFmpeg concat files require single-quote escaping for paths containing
    # apostrophes; otherwise Cartoon/Story titles can break assembly.
    def concat_escape(path: str) -> str:
        return path.replace("'", "'\\''")
    concat_file.write_text("".join(f"file '{concat_escape(r['clip_path'])}'\n" for r in valid_clips),
                            encoding="utf-8")
    out_path = settings.path(settings.data_dir, "output") / f"story_v{video_id}.mp4"

    # Concatenate + add music if available.
    if music_path and Path(music_path).exists():
        # Concat video, then add music bed.
        base_path = work / "base.mp4"
        base_rc, _, base_err = await run_cmd([
            ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", str(base_path),
        ])
        if base_rc != 0 or not base_path.exists() or base_path.stat().st_size < 1000:
            return {"success": False, "reason": f"story concat failed: {base_err[-500:]}"}
        total_dur = await probe_duration(str(base_path)) or 60.0
        music_rc, _, music_err = await run_cmd([
            ffmpeg_bin(), "-y", "-i", str(base_path),
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex",
            f"[1:a]volume=0.15,afade=t=in:d=2,afade=t=out:st={max(total_dur-3,0):.1f}:d=3[mus];"
            f"[0:a][mus]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out_path),
        ])
        if music_rc != 0 or not out_path.exists() or out_path.stat().st_size < 1000:
            return {"success": False, "reason": f"story music assembly failed: {music_err[-500:]}"}
    else:
        concat_rc, _, concat_err = await run_cmd([
            ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", str(out_path),
        ])
        if concat_rc != 0 or not out_path.exists() or out_path.stat().st_size < 1000:
            return {"success": False, "reason": f"story concat failed: {concat_err[-500:]}"}

    total_duration = await probe_duration(str(out_path)) or 0.0
    if total_duration <= 0:
        return {"success": False, "reason": "story output has no readable duration"}
    log.info("story video assembled: %s (%.1fs, %d scenes)",
             out_path.name, total_duration, len(valid_clips))
    return {"success": True, "path": str(out_path),
            "duration": total_duration, "scenes": len(valid_clips),
            "story": story}


async def create_ai_story_video(prompt: str, genre: str = "kids_fairy_tale",
                                 scene_count: int = 5,
                                 target_seconds: int = 60,
                                 language: str = "en",
                                 music_path: str | None = None,
                                 video_id: int = 0) -> dict:
    """Full flow: generate story → generate images + voice → assemble video.

    This is the main entry point for the AI Story Video Generator.
    """
    # Step 1: generate the story.
    log.info("generating story: '%s' (genre=%s, scenes=%d, lang=%s)",
             prompt[:50], genre, scene_count, language)
    story = await generate_story(prompt, genre, scene_count, target_seconds, language)
    log.info("story generated: '%s' (%d scenes)", story.get("title", "untitled"),
             len(story.get("scenes", [])))

    # Step 2: assemble the video.
    result = await assemble_story_video(story, video_id, language, music_path)
    if result.get("success"):
        result["story"] = story
    return result
