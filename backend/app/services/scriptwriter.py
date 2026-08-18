"""AI script writer.

LLM mode : retention-engineered scripts with hook -> setup -> escalation ->
           payoff -> CTA, scene-by-scene with visual search queries.
Mock mode: a structured template engine producing the same JSON shape,
           so every downstream service behaves identically.

v1.3 upgrades:
  - Cinematic mode: when settings.cinematic_mode is True, the LLM prompt
    asks for a movie-like narrative arc (cold open, rising tension,
    climax, resolution) with rich sensory descriptions for the editor's
    visual query builder.
  - Language-specific instructions: Urdu scripts are told to use simple
    conversational Urdu (Roman + Arabic script handled by the LLM),
    avoid English-mixed sentences that confuse TTS, and respect cultural
    idioms. English scripts use punchy YouTube-native phrasing.
  - Strategy-aware: when the channel has learned insights from the
    monitor (top-performing hooks / durations), they are injected into
    the prompt as inspiration.
"""
from __future__ import annotations

import random

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("script")

HOOK_STYLES = ["question", "bold_claim", "mystery", "statistic", "story_cold_open"]

_STYLE_GUIDES = {
    "technology": "crisp, futuristic, respectful of the viewer's intelligence",
    "finance": "trustworthy, concrete numbers, zero hype",
    "health": "warm, science-backed, actionable",
    "space": "awe-driven, cinematic vocabulary",
    "history": "narrative, dramatic pacing, vivid scenes — like a documentary",
    "science": "curious, simple analogies, wonder",
    "education": "clear, structured, memorable",
    "entertainment": "playful, fast-paced, surprising",
    "gaming": "energetic, insider references, hype-driven",
    "lifestyle": "warm, relatable, aspirational",
    "news": "factual, balanced, urgent",
    "music": "rhythmic, evocative, mood-driven",
}

# Language-specific instruction blocks sent to the LLM.
_LANGUAGE_GUIDES = {
    "ur": (
        "اُردو میں لکھیں۔ خالص اُردو استعمال کریں، انگریزی الفاظ کا مکس نہ کریں۔ "
        "بول چال کی اُردو، سادہ فقرے، ہر فقرہ 15-20 الفاظ کا۔ "
        "تشکیل (diacritics) کا استعمال نہ کریں — Edge-TTS خود بخود درست تلفظ کرے گا۔ "
        "ہر منظر کے آخر میں ایک مختصر تاثر (visual cue) شامل کریں جو ایڈیٹر کے لیے رہنما ہو۔"
    ),
    "hi": (
        "हिंदी में लिखें। सरल बोलचाल की हिंदी, हर वाक्य 15-20 शब्दों का। "
        "अंग्रेज़ी शब्दों का मिक्स न करें ताकि TTS साफ़ बोल सके। "
        "हर दृश्य के अंत में एक छोटा विज़ुअल क्यू दें।"
    ),
    "en": (
        "Write in clear, punchy YouTube-native English. Conversational tone, "
        "every sentence under 20 words. Use second person ('you') liberally. "
        "End every scene with a 3-6 word visual_query for stock footage search."
    ),
    "es": "Escribe en español natural, conversacional. Frases cortas, máximo 20 palabras.",
    "ar": "اكتب بالعربية الفصحى المبسطة. جمل قصيرة، 15-20 كلمة لكل جملة.",
    "de": "Schreibe in natürlichem, gesprochenem Deutsch. Kurze Sätze, max. 20 Wörter.",
    "fr": "Écris en français naturel et parlé. Phrases courtes, 20 mots max.",
}


def _speech_words_per_second(language: str) -> float:
    """Conservative spoken-word budget used to size narration before TTS."""
    lang = (language or "en").lower().split("-")[0]
    return {"ur": 1.85, "hi": 1.95, "ar": 1.9}.get(lang, 2.45)


def _expand_template_narration(topic: str, beat: str, line: str,
                               target_words: int, language: str = "en") -> str:
    """Expand deterministic fallback narration without repeating one sentence.

    The old fallback used six short lines regardless of the requested duration,
    producing ~40-second videos for a 150-second target. This keeps the
    fallback offline and deterministic while giving each beat a coherent,
    topic-specific explanation.
    """
    additions = {
        "hook": [
            f"At first glance, {topic.lower()} seems straightforward, but the details hide a much bigger story.",
            "That first impression is exactly why so many people miss what is really happening.",
            "Stay with the explanation, because the most useful insight arrives after the obvious answer.",
        ],
        "setup": [
            f"To understand {topic.lower()}, start with the basic idea and then follow how the pieces connect.",
            "This foundation matters because later decisions only make sense when the context is clear.",
            "Think of it as a map: every small detail points toward the larger conclusion.",
        ],
        "context": [
            "Older explanations were useful, but new evidence has made the picture more precise.",
            "Researchers compare multiple examples, remove misleading assumptions, and look for the pattern that survives.",
            "The important lesson is not one isolated fact; it is how several facts reinforce each other.",
        ],
        "escalation": [
            "Now the story becomes more interesting, because a small change can produce a surprisingly large effect.",
            "This is where common advice often fails: it ignores timing, trade-offs, and the conditions around the result.",
            "Once those hidden variables are visible, the outcome is easier to predict and easier to use.",
        ],
        "payoff": [
            f"The practical takeaway for {topic.lower()} is simple: focus on the evidence, not the loudest claim.",
            "Use that principle to make a better decision, test the result, and adjust when new information appears.",
            "A clear mental model is more valuable than a dramatic headline because it keeps working in real situations.",
        ],
        "cta": [
            "If this explanation helped, save it and share it with someone who is still asking the same question.",
            "The next video will build on this idea with another real example and a practical comparison.",
            "Subscribe for more clear, evidence-led stories without exaggerated promises or invented numbers.",
        ],
    }
    words = (line + " " + " ".join(additions.get(beat, additions["context"]))).split()
    while len(words) < target_words:
        words.extend(additions.get(beat, additions["context"])[len(words) % 3].split())
    return " ".join(words[:target_words])


def _scenes_from_template(topic: str, niche: str, target_seconds: int, hook_style: str,
                           language: str = "en") -> list[dict]:
    """Generate template scenes with DIFFERENT visual queries per scene.

    v1.7 fix: previously every scene got the same visual_query
    ("{niche} {topic} cinematic"), which caused the media fetcher to
    return the SAME cached clip for every scene. Now each beat has its
    own distinct visual_query so the editor gets variety.
    """
    n_scenes = max(4, min(8, target_seconds // 25))
    topic_word = topic.split()[0].lower() if topic.split() else niche
    beats = [
        ("hook", f"What if everything you thought about {topic.lower()} was only half the story?",
         f"{niche} abstract concept cinematic dark"),
        ("setup", f"Let's set the scene. {topic} — it sounds simple, but the details are where it gets fascinating.",
         f"{niche} research laboratory cinematic"),
        ("context", f"For years, experts treated this as settled. Then new evidence flipped the narrative completely.",
         f"{niche} vintage archive footage cinematic"),
        ("escalation", f"And here's where it gets wild: the deeper researchers looked, the stranger the answers became.",
         f"{niche} close-up detail cinematic dramatic"),
        ("payoff", f"So what's the real takeaway? The truth about {topic.lower()} turns out to be more useful than the myth.",
         f"{niche} sunrise revelation cinematic"),
        ("cta", "If this changed how you see things, subscribe — tomorrow's video goes even deeper.",
         f"{niche} city skyline night cinematic"),
    ]
    scenes = []
    speech_budget = max(15.0, target_seconds - max(0, n_scenes - 1) * 0.45)
    target_words_per_scene = max(18, round(speech_budget * _speech_words_per_second(language) / n_scenes))
    for i in range(n_scenes):
        kind, line, vq = beats[min(i, len(beats) - 1)]
        if (language or "en").lower().startswith("ur"):
            line = f"Aaj hum {topic} ke bare mein aik aham baat seedhi misaalon ke saath samjhenge۔ {line}"
        narration = _expand_template_narration(topic, kind, line, target_words_per_scene, language)
        scenes.append({
            "index": i,
            "beat": kind,
            "narration": narration,
            "visual_query": vq,
            "emphasis": [w for w in line.split() if len(w) > 7][:2],
        })
    return scenes


def _template_script(topic: str, niche: str, language: str, target_seconds: int,
                     hook_style: str, content_type: str | None = None) -> dict:
    # v1.8: if content_type is set and not "explainer", use content_types templates.
    if content_type and content_type != "explainer":
        from .content_types import get_template_beats
        beats = get_template_beats(content_type, topic)
        n_scenes = max(4, min(12, target_seconds // 25))
        scenes = []
        for i in range(n_scenes):
            beat, narration, vq = beats[min(i, len(beats) - 1)]
            if (language or "en").lower().startswith("ur"):
                narration = f"{topic} ko samajhne ke liye is qadam ka amli matlab dekhte hain۔ {narration}"
            target_words = max(
                18,
                round(max(15.0, target_seconds - max(0, n_scenes - 1) * 0.45)
                      * _speech_words_per_second(language) / n_scenes),
            )
            narration = _expand_template_narration(topic, beat, narration, target_words, language)
            scenes.append({
                "index": i,
                "beat": beat,
                "narration": narration,
                "visual_query": vq,
                "emphasis": [w for w in narration.split() if len(w) > 7][:2],
            })
        return {
            "topic": topic, "niche": niche, "language": language,
            "hook_style": hook_style, "content_type": content_type,
            "title_options": [clamp(f"{topic} — {content_type.title()}", 95),
                              clamp(f"The Truth About {topic}", 95)],
            "scenes": scenes,
            "purpose": f"Viewer ko {topic} ka clear context, practical meaning aur actionable takeaway dena.",
            "takeaways": ["bunyadi concept samajhna", "evidence ke mutabiq sochna", "seekhi hui baat ko amli zindagi mein azmana"],
            "estimated_seconds": target_seconds,
            "engine": "template",
        }
    # Default explainer template.
    scenes = _scenes_from_template(topic, niche, target_seconds, hook_style, language)
    return {
        "topic": topic,
        "niche": niche,
        "language": language,
        "hook_style": hook_style,
        "title_options": [
            clamp(f"The Untold Truth About {topic}", 95),
            clamp(f"{topic} — Explained Like Never Before", 95),
            clamp(f"Why {topic} Changes Everything", 95),
        ],
        "scenes": scenes,
        "purpose": f"Viewer ko {topic} ka clear context, practical meaning aur actionable takeaway dena.",
        "takeaways": ["bunyadi concept samajhna", "evidence ke mutabiq sochna", "seekhi hui baat ko amli zindagi mein azmana"],
        "estimated_seconds": target_seconds,
        "engine": "template",
    }


async def write_script(
    topic: str,
    niche: str,
    language: str = "en",
    target_seconds: int = 150,
    hook_style: str | None = None,
    strategy_context: str = "",
    learned_inspiration: str = "",
    scene_count: int | None = None,
    content_type: str | None = None,
) -> dict:
    """Generate a complete scene-by-scene script (LLM or template).

    `learned_inspiration` is optional text from the YouTube monitor — patterns
    observed in 2M+ view videos of this niche. The LLM is asked to draw
    inspiration from them WITHOUT copying.

    `scene_count` overrides the auto-calculated scene count (default: based
    on target_seconds). Use this when the user wants a specific number of
    scenes regardless of video length.
    """
    hook_style = hook_style or random.choice(HOOK_STYLES)
    style = _STYLE_GUIDES.get(niche, "engaging, clear, energetic")
    # v1.7: allow manual scene count override.
    if scene_count and 3 <= scene_count <= 12:
        n_scenes = scene_count
    else:
        n_scenes = max(4, min(12, target_seconds // 25))
    lang_guide = _LANGUAGE_GUIDES.get((language or "en").lower().split("-")[0],
                                       _LANGUAGE_GUIDES["en"])

    cinematic_block = ""
    if settings.cinematic_mode:
        cinematic_block = (
            "CINEMATIC MODE: structure the script like a short documentary film. "
            "Open with a sensory cold-open (a single striking image + sound). "
            "Build tension scene by scene. Use vivid visual_queries that suggest "
            "specific cinematic shots — 'slow drone over desert at dawn', "
            "'close-up of historical artifact panning', 'aerial view of city at night'. "
            "Each scene's visual_query should evoke a film still, not a stock-photo cliché."
        )

    inspiration_block = ""
    if learned_inspiration:
        inspiration_block = (
            f"\n\nINSPIRATION (draw from, do NOT copy):\n{learned_inspiration}\n"
            "Use these patterns as creative fuel — never reproduce them verbatim."
        )

    prompt = [
        {"role": "system", "content": (
            "You are an elite YouTube scriptwriter who maximizes audience retention. "
            "Respond ONLY with JSON: {title_options: [3 strings <=95 chars], "
            "scenes: [{index, beat, narration, visual_query, emphasis}]}. "
            f"Rules: scene 0 is a 5-second hook creating an open loop; narration is "
            f"conversational spoken text, approximately {max(18, round(max(15.0, target_seconds - max(0, n_scenes - 1) * 0.45) * _speech_words_per_second(language) / n_scenes))} words per scene; exactly "
            f"{n_scenes} scenes; beats escalate curiosity; final scene is a short CTA; "
            "visual_query is a 3-8 word cinematic stock-footage search phrase; "
            "emphasis lists 1-2 power words from the narration to highlight in captions. "
            f"{cinematic_block}\n{lang_guide}"
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\nNiche: {niche}\nTone: {style}\nLanguage: {language}\n"
            f"Hook style: {hook_style}\nTarget length: ~{target_seconds} seconds spoken.\n"
            f"{strategy_context}{inspiration_block}"
        )},
    ]
    data = await llm.chat_json(prompt, temperature=0.85)

    if isinstance(data, dict) and data.get("scenes"):
        scenes = []
        for i, s in enumerate(data["scenes"][: n_scenes]):
            scenes.append({
                "index": i,
                "beat": str(s.get("beat", "body"))[:24],
                "narration": str(s.get("narration", "")).strip(),
                "visual_query": str(s.get("visual_query", f"{niche} cinematic"))[:80],
                "emphasis": [str(w) for w in s.get("emphasis", [])][:3],
            })
        scenes = [s for s in scenes if s["narration"]]
        if scenes:
            log.info("script written by LLM (%d scenes, hook=%s, lang=%s)",
                     len(scenes), hook_style, language)
            return {
                "topic": topic, "niche": niche, "language": language,
                "hook_style": hook_style,
                "title_options": [clamp(str(t), 95) for t in data.get("title_options", [])][:3]
                                 or [clamp(topic, 95)],
                "scenes": scenes,
                "estimated_seconds": target_seconds,
                "engine": "llm",
            }

    log.info("LLM unavailable — using template script engine (hook=%s, type=%s)",
             hook_style, content_type or "explainer")
    return _template_script(topic, niche, language, target_seconds, hook_style,
                            content_type=content_type)
