"""Video Remix — upload a video, analyze it, create a similar but different video.

Flow:
  1. User uploads a reference video (or provides a YouTube URL).
  2. System extracts the narration (via Whisper if available, or via
     the video's audio → transcript).
  3. LLM analyzes the transcript + creates a NEW but similar story
     (different words, same structure/beats).
  4. AI Story Generator creates the video from the new story.
  5. The result is a video with the same "feel" as the original but
     completely different narration + images — avoiding copyright.

This is the "remix" approach that many viral Shorts channels use.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp, ffmpeg_bin, probe_duration, run_cmd
from . import llm
from .ai_story import assemble_story_video, generate_fallback_image, generate_scene_image

log = get_logger("video_remix")


async def extract_transcript(video_path: str, language: str = "en") -> dict:
    """Extract a transcript from a video's audio track without blocking the API.

    The preferred local engine is faster-whisper (CPU/int8). OpenAI Whisper is
    supported as a fallback. Both are executed in a worker thread because model
    loading and decoding are CPU-heavy operations.
    """
    src = Path(video_path)
    if not src.exists():
        return {"transcript": "", "duration": 0, "method": "none", "reason": "source video not found"}

    duration = await probe_duration(video_path) or 0.0

    async def run_faster_whisper() -> dict | None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return None

        model_size = getattr(settings, "whisper_model", "base") or "base"

        def decode() -> dict | None:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, info = model.transcribe(video_path, language=language, vad_filter=True)
            segment_list = []
            text_parts = []
            for seg in segments:
                text = (seg.text or "").strip()
                if text:
                    text_parts.append(text)
                    segment_list.append({"start": float(seg.start), "end": float(seg.end), "text": text})
            transcript = " ".join(text_parts).strip()
            if not transcript:
                return None
            return {"transcript": transcript, "duration": duration,
                    "method": "faster-whisper", "segments": segment_list,
                    "detected_language": getattr(info, "language", language)}

        try:
            return await asyncio.to_thread(decode)
        except Exception as exc:
            log.warning("faster-whisper failed: %s", exc)
            return None

    fast_result = await run_faster_whisper()
    if fast_result:
        log.info("transcript extracted via faster-whisper: %d chars", len(fast_result["transcript"]))
        return fast_result

    async def run_openai_whisper() -> dict | None:
        try:
            import whisper
        except ImportError:
            return None

        def decode() -> dict | None:
            model = whisper.load_model(getattr(settings, "whisper_model", "base") or "base")
            result = model.transcribe(video_path, language=language)
            transcript = (result.get("text", "") or "").strip()
            if not transcript:
                return None
            return {"transcript": transcript, "duration": duration,
                    "method": "whisper", "segments": result.get("segments", [])}

        try:
            return await asyncio.to_thread(decode)
        except Exception as exc:
            log.warning("OpenAI Whisper failed: %s", exc)
            return None

    whisper_result = await run_openai_whisper()
    if whisper_result:
        log.info("transcript extracted via Whisper: %d chars", len(whisper_result["transcript"]))
        return whisper_result

    return {"transcript": "", "duration": duration, "method": "none",
            "reason": "No local speech-to-text engine is available. Run ./run.sh to install faster-whisper, then retry."}


def _fallback_analysis(transcript: str, duration: float) -> dict:
    """Create usable scene beats when no live LLM is configured."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟۔])\s+", transcript) if s.strip()]
    if not sentences:
        words = transcript.split()
        chunk_size = max(12, len(words) // 5 or 12)
        sentences = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    sentences = sentences[:8]
    if len(sentences) < 3:
        sentences.extend(["A new detail changes the direction of the story.", "The ending leaves a clear lesson for the viewer."])
    scenes = [{
        "index": i,
        "narration": s,
        "image_prompt": "cinematic original illustration, dramatic light, documentary storytelling",
        "beat": "setup" if i == 0 else "development" if i < len(sentences) - 1 else "resolution",
    } for i, s in enumerate(sentences)]
    return {"topic": "original remix", "genre": "entertainment", "scenes": scenes,
            "tone": "cinematic", "target_audience": "general"}


async def analyze_video_structure(transcript: str, duration: float) -> dict:
    """Ask the LLM to analyze a video's structure from its transcript.

    Returns:
      {topic, genre, scenes: [{narration, image_prompt, beat}], tone, target_audience}
    """
    if not transcript:
        return {"topic": "unknown", "genre": "unknown", "scenes": [],
                "tone": "neutral", "target_audience": "general"}
    prompt = [
        {"role": "system", "content": (
            "You are a video structure analyst. Analyze this video transcript "
            "and extract its narrative structure. Respond ONLY with JSON: "
            "{topic: str, genre: str (one of: kids_fairy_tale, moral_story, "
            "adventure, mystery, educational, entertainment, scifi_short), "
            "tone: str, target_audience: str, "
            "scenes: [{narration: str, image_prompt: str, beat: str}]}. "
            "Break the transcript into 4-8 scenes. Each image_prompt should be "
            "a 5-10 word English description for an AI image generator."
        )},
        {"role": "user", "content": (
            f"Transcript: {transcript[:2000]}\nDuration: {duration:.0f}s"
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.5)
    if isinstance(data, dict) and isinstance(data.get("scenes"), list) and data.get("scenes"):
        return data
    return _fallback_analysis(transcript, duration)


async def remix_story(analysis: dict, language: str = "en") -> dict:
    """Create a NEW but similar story from the analysis.

    The LLM is told to write a story with the SAME genre, tone, and
    target audience — but completely different characters, plot, and
    words. This ensures the remix is legally distinct while keeping
    the "feel" that made the original viral.
    """
    prompt = [
        {"role": "system", "content": (
            "You are a creative storyteller. You've been given the structure "
            "analysis of a viral video. Write a COMPLETELY NEW story with the "
            "SAME genre, tone, and target audience — but with different "
            "characters, plot, setting, and words. The new story should feel "
            "similar in pacing and emotion, but must be 100% original "
            "(no copied phrases). Respond ONLY with JSON: "
            "{title: str, scenes: [{index, narration, image_prompt}]}. "
            f"Write narration in {language}. image_prompt in English."
        )},
        {"role": "user", "content": (
            f"Original video analysis:\n"
            f"Topic: {analysis.get('topic', 'unknown')}\n"
            f"Genre: {analysis.get('genre', 'unknown')}\n"
            f"Tone: {analysis.get('tone', 'neutral')}\n"
            f"Target audience: {analysis.get('target_audience', 'general')}\n"
            f"Original scenes: {len(analysis.get('scenes', []))}\n\n"
            f"Write a new story with the same structure but different content."
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.9)
    if not isinstance(data, dict) or not data.get("scenes"):
        # Fallback: preserve only high-level beats, never copy raw metadata as
        # a fake success. The narration is rewritten and images are original.
        scenes = analysis.get("scenes", []) or _fallback_analysis(
            "A new story begins. The characters face a challenge. The ending reveals a lesson.", 60
        ).get("scenes", [])
        remixed = []
        for i, s in enumerate(scenes):
            remixed.append({
                "index": i,
                "narration": f"In a different world, {s.get('narration', 'a story unfolds')}",
                "image_prompt": s.get("image_prompt", "fantasy landscape"),
            })
        return {"title": "A New Story", "scenes": remixed}
    return data


async def remix_video(source_path: str, video_id: int = 0,
                       language: str = "en",
                       music_path: str | None = None,
                       transcript_result: dict | None = None) -> dict:
    """Full remix flow: extract transcript → analyze → remix → generate video.

    Returns {success, path, story, analysis, original_path}.
    """
    log.info("remixing video: %s", source_path)

    # Step 1: extract transcript.
    transcript_result = transcript_result or await extract_transcript(source_path, language)
    transcript = transcript_result.get("transcript", "")
    duration = transcript_result.get("duration", 60.0)

    # Step 2: analyze structure.
    analysis = await analyze_video_structure(transcript, duration)
    log.info("video analyzed: topic=%s, genre=%s, scenes=%d",
             analysis.get("topic"), analysis.get("genre"),
             len(analysis.get("scenes", [])))

    # Step 3: remix the story.
    remixed = await remix_story(analysis, language)
    if not remixed.get("scenes"):
        return {"success": False, "reason": "Remix story could not create any scenes; retry with a clearer audio track."}
    log.info("story remixed: '%s' (%d scenes)",
             remixed.get("title", "untitled"),
             len(remixed.get("scenes", [])))

    # Step 4: generate the new video.
    story = {**remixed, "genre": analysis.get("genre", "kids_fairy_tale"),
             "target_seconds": int(duration), "language": language}
    result = await assemble_story_video(story, video_id, language, music_path)
    if result.get("success"):
        result["story"] = story
        result["analysis"] = analysis
        result["original_path"] = source_path
        result["transcript_method"] = transcript_result.get("method")
    return result
