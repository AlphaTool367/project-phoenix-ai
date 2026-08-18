"""Video repurposing — convert one video into 7+ content formats.

After a video is produced, this module generates:
  - Blog post (Markdown)
  - Twitter/X thread (10 tweets)
  - LinkedIn article
  - Reddit post
  - Medium article
  - Email newsletter
  - Podcast audio (extract from video)

All text-based formats use the LLM to transform the video's script into
the target format. The podcast format simply extracts the audio track
from the rendered video via FFmpeg.
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp, ffmpeg_bin, run_cmd
from . import llm

log = get_logger("repurposing")


async def to_blog_post(script: dict, video_title: str) -> str:
    """Convert a video script into a Markdown blog post."""
    scenes = script.get("scenes", [])
    narration = "\n\n".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are a blog writer. Convert this YouTube video script into a "
            "well-structured Markdown blog post with an H1 title, H2 sections, "
            "an intro, a conclusion, and a call-to-action. Keep the same "
            "information but make it read naturally as an article (not a script). "
            "Respond ONLY with the Markdown — no preamble."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript:\n{narration}"},
    ]
    text = await llm.chat(prompt, temperature=0.6)
    return text or f"# {video_title}\n\n{narration}"


async def to_twitter_thread(script: dict, video_title: str) -> list[str]:
    """Convert a video script into a Twitter/X thread (list of tweets)."""
    scenes = script.get("scenes", [])
    narration = " ".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are a Twitter expert. Convert this video script into a thread "
            "of 8-10 tweets. Each tweet must be ≤280 chars. The first tweet is "
            "the hook (must make people want to read the thread). Respond ONLY "
            "with a JSON array of strings."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript: {narration}"},
    ]
    data = await llm.chat_json(prompt, temperature=0.7)
    if isinstance(data, list):
        return [clamp(str(t), 280) for t in data][:10]
    # Fallback: split narration into chunks.
    words = narration.split()
    tweets = []
    chunk = []
    for w in words:
        chunk.append(w)
        if len(" ".join(chunk)) > 250:
            tweets.append(" ".join(chunk))
            chunk = []
    if chunk:
        tweets.append(" ".join(chunk))
    return tweets[:10]


async def to_linkedin_article(script: dict, video_title: str) -> str:
    """Convert a video script into a LinkedIn article."""
    scenes = script.get("scenes", [])
    narration = "\n\n".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are a LinkedIn content writer. Convert this video script into "
            "a professional LinkedIn article. Use a hook opening, 3 key "
            "insights with bold headers, and a thought-provoking closing "
            "question. Keep it under 1500 chars. Respond ONLY with the article text."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript:\n{narration}"},
    ]
    text = await llm.chat(prompt, temperature=0.6)
    return text or narration


async def to_reddit_post(script: dict, video_title: str) -> dict:
    """Convert a video script into a Reddit post (title + body)."""
    scenes = script.get("scenes", [])
    narration = "\n\n".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are a Reddit expert. Convert this video script into a Reddit "
            "post. Respond ONLY with JSON: {title (≤100 chars, no clickbait), "
            "subreddit (suggested), body (markdown, ≤4000 chars)}."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript:\n{narration}"},
    ]
    data = await llm.chat_json(prompt, temperature=0.6)
    if isinstance(data, dict):
        return {
            "title": clamp(str(data.get("title", video_title)), 100),
            "subreddit": str(data.get("subreddit", "interestingasfuck")),
            "body": clamp(str(data.get("body", narration)), 4000),
        }
    return {"title": video_title, "subreddit": "todayilearned", "body": narration}


async def to_medium_article(script: dict, video_title: str) -> str:
    """Convert a video script into a Medium article (Markdown)."""
    scenes = script.get("scenes", [])
    narration = "\n\n".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are a Medium writer. Convert this video script into a "
            "publication-ready Medium article in Markdown. Include a subtitle, "
            "H2 sections, blockquotes for key insights, and a 'Key Takeaways' "
            "section at the end. Respond ONLY with Markdown."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript:\n{narration}"},
    ]
    text = await llm.chat(prompt, temperature=0.6)
    return text or f"# {video_title}\n\n{narration}"


async def to_newsletter(script: dict, video_title: str) -> str:
    """Convert a video script into an email newsletter."""
    scenes = script.get("scenes", [])
    narration = "\n\n".join(s.get("narration", "") for s in scenes)
    prompt = [
        {"role": "system", "content": (
            "You are an email newsletter writer. Convert this video script into "
            "a short, engaging newsletter email. Include a subject line, a "
            "personal greeting, 2-3 short paragraphs, and a 'Watch the video' "
            "CTA with a placeholder link. Keep it under 800 chars. Respond ONLY "
            "with the email text (subject line on the first line)."
        )},
        {"role": "user", "content": f"Title: {video_title}\n\nScript:\n{narration}"},
    ]
    text = await llm.chat(prompt, temperature=0.6)
    return text or f"Subject: {video_title}\n\n{narration}"


async def to_podcast(video_file_path: str, out_path: str | None = None) -> dict:
    """Extract the audio track from a rendered video as a podcast MP3.

    Uses FFmpeg to extract + convert to MP3 at 128kbps.
    """
    src = Path(video_file_path)
    if not src.exists():
        return {"created": False, "reason": "video file not found"}
    if out_path is None:
        out_path = str(src.with_suffix(".podcast.mp3"))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rc, _, err = await run_cmd([
        ffmpeg_bin(), "-y", "-i", str(src),
        "-vn", "-acodec", "libmp3lame", "-ab", "128k", "-ar", "44100",
        str(out),
    ])
    if rc != 0:
        return {"created": False, "reason": f"ffmpeg failed: {err[-200:]}"}
    return {"created": True, "path": str(out), "size_mb": round(out.stat().st_size / 1e6, 1)}


async def repurpose_all(script: dict, video_title: str,
                         video_file_path: str | None = None) -> dict:
    """Generate ALL repurposed formats at once.

    Returns a dict with keys: blog, twitter, linkedin, reddit, medium,
    newsletter, podcast.
    """
    results: dict = {}
    # Text formats (parallel).
    import asyncio
    tasks = {
        "blog": to_blog_post(script, video_title),
        "twitter": to_twitter_thread(script, video_title),
        "linkedin": to_linkedin_article(script, video_title),
        "reddit": to_reddit_post(script, video_title),
        "medium": to_medium_article(script, video_title),
        "newsletter": to_newsletter(script, video_title),
    }
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for (key, _), result in zip(tasks.items(), gathered):
        if isinstance(result, Exception):
            results[key] = f"[Error: {result}]"
        else:
            results[key] = result
    # Podcast (needs video file).
    if video_file_path:
        results["podcast"] = await to_podcast(video_file_path)
    else:
        results["podcast"] = {"created": False, "reason": "no video file"}
    return results
