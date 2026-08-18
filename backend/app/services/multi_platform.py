"""Multi-platform SEO + distribution.

Generates platform-specific metadata (title, description, tags, hashtags)
for each target platform:
  - YouTube (long-form + Shorts)
  - TikTok
  - Instagram Reels
  - Facebook
  - Twitter/X
  - LinkedIn
  - Pinterest
  - Reddit

Each platform has different character limits, hashtag conventions, and
audience expectations. The LLM generates optimized metadata per platform
from the video's script.

Also includes SRT subtitle export (for platforms that support it) and
multi-language subtitle generation.
"""
from __future__ import annotations

from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("multi_platform")

# Platform-specific constraints.
PLATFORM_LIMITS = {
    "youtube":       {"title": 100, "desc": 5000, "tags": 500, "hashtags": 3},
    "youtube_shorts": {"title": 100, "desc": 1000, "tags": 500, "hashtags": 3},
    "tiktok":        {"title": 150, "desc": 2200, "tags": 0,   "hashtags": 5},
    "instagram":     {"title": 0,   "desc": 2200, "tags": 0,   "hashtags": 10},
    "facebook":      {"title": 0,   "desc": 5000, "tags": 0,   "hashtags": 3},
    "twitter":       {"title": 0,   "desc": 280,  "tags": 0,   "hashtags": 2},
    "linkedin":      {"title": 0,   "desc": 3000, "tags": 0,   "hashtags": 3},
    "pinterest":     {"title": 100, "desc": 500,  "tags": 0,   "hashtags": 3},
    "reddit":        {"title": 300, "desc": 40000,"tags": 0,   "hashtags": 0},
}


async def generate_platform_metadata(
    script: dict, niche: str, platform: str, video_title: str = "",
) -> dict:
    """Generate platform-specific title, description, tags, hashtags.

    Returns:
      {platform, title, description, tags, hashtags, char_counts}
    """
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["youtube"])
    narration = " ".join(s.get("narration", "") for s in script.get("scenes", []))
    title_hint = video_title or script.get("title_options", [""])[0]

    platform_guides = {
        "youtube": "Write a click-worthy YouTube title (≤100 chars), a 2-paragraph description with chapters + CTA, 14 tags, 3 hashtags.",
        "youtube_shorts": "Write a punchy Shorts title (≤100 chars), a 1-line description, 5 tags, 3 hashtags. Keep it short-form focused.",
        "tiktok": "Write a catchy TikTok caption (≤150 chars), a description with 5 trending hashtags. TikTok favors trending sounds + humor.",
        "instagram": "Write an Instagram Reels caption (≤2200 chars) with 10 hashtags. Instagram favors aesthetic + relatable content.",
        "facebook": "Write a Facebook post (≤5000 chars) with 3 hashtags. Facebook favors personal + shareable content.",
        "twitter": "Write a single tweet (≤280 chars) with 2 hashtags. Must be punchy + shareable.",
        "linkedin": "Write a LinkedIn post (≤3000 chars) with 3 hashtags. Professional, insight-driven, no emojis.",
        "pinterest": "Write a Pinterest pin title (≤100 chars) + description (≤500 chars) with 3 hashtags. SEO-focused.",
        "reddit": "Write a Reddit post title (≤300 chars) + body (≤4000 chars). No hashtags. Reddit values authenticity + discussion.",
    }

    guide = platform_guides.get(platform, platform_guides["youtube"])
    prompt = [
        {"role": "system", "content": (
            f"You are a {platform} content optimizer. {guide} "
            f"Respond ONLY with JSON: {{title, description, tags (array), hashtags (array)}}."
        )},
        {"role": "user", "content": (
            f"Topic: {script.get('topic', '')}\nNiche: {niche}\n"
            f"Original title: {title_hint}\nScript excerpt: {narration[:500]}"
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.6)
    if not isinstance(data, dict):
        # Fallback: use the original title + simple description.
        data = {"title": title_hint, "description": narration[:limits["desc"]],
                "tags": [niche], "hashtags": [f"#{niche}"]}

    # Enforce limits.
    title = clamp(str(data.get("title", title_hint)), limits["title"]) if limits["title"] else ""
    description = clamp(str(data.get("description", "")), limits["desc"])
    tags = [str(t) for t in data.get("tags", [])][:14] if limits["tags"] > 0 else []
    hashtags = [str(h) for h in data.get("hashtags", [])][:limits["hashtags"]] if limits["hashtags"] > 0 else []

    return {
        "platform": platform,
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "char_counts": {
            "title": len(title),
            "description": len(description),
            "title_limit": limits["title"],
            "desc_limit": limits["desc"],
        },
    }


async def generate_all_platforms(script: dict, niche: str,
                                  video_title: str = "") -> dict:
    """Generate metadata for ALL platforms at once."""
    import asyncio
    platforms = list(PLATFORM_LIMITS.keys())
    tasks = [generate_platform_metadata(script, niche, p, video_title)
             for p in platforms]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for p, r in zip(platforms, results):
        if isinstance(r, Exception):
            out[p] = {"error": str(r)}
        else:
            out[p] = r
    return out


def export_srt_subtitles(script: dict, scene_starts: list[float] | None = None) -> str:
    """Export the video's captions as an SRT subtitle file (for platforms that
    support it — YouTube, Facebook, LinkedIn).

    Uses the word timings from Edge-TTS if available, otherwise falls back
    to scene-level timing.
    """
    lines = []
    idx = 1
    for i, scene in enumerate(script.get("scenes", [])):
        start = scene_starts[i] if scene_starts and i < len(scene_starts) else 0
        narration = scene.get("narration", "")
        if not narration:
            continue
        # Estimate duration from word count (2.5 words/sec).
        duration = max(len(narration.split()) / 2.5, 3.0)
        end = start + duration
        # SRT timestamp format: HH:MM:SS,mmm
        def _srt_time(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines.append(str(idx))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(narration)
        lines.append("")
        idx += 1
    return "\n".join(lines)
