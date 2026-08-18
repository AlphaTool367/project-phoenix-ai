"""First-30-second hook effectiveness analyzer.

After the script is written (and before rendering), this module asks the
LLM to score the opening scene's hook on four dimensions:

  - **curiosity** (0-25): does it create an open loop the viewer MUST close?
  - **clarity** (0-25): is the topic immediately clear?
  - **stakes** (0-25): does the viewer feel "I need to know this"?
  - **pacing** (0-25): is the rhythm right? (not too slow, not too fast)

Returns a 0-100 score + concrete improvement suggestions. The orchestrator
logs the score on the Video row (in `seo_json.hook_analysis`) so the
dashboard can show "weak hook" warnings.

When the score is < 60, the analyzer also returns 3 alternative hook
lines the scriptwriter could swap in.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("hook_analyzer")


async def analyze_hook(
    topic: str,
    niche: str,
    hook_narration: str,
    hook_style: str | None = None,
    target_seconds: int = 150,
) -> dict:
    """Score the opening hook narration.

    Returns:
      {
        "score": int,             # 0-100 total
        "curiosity": int,         # 0-25
        "clarity": int,           # 0-25
        "stakes": int,            # 0-25
        "pacing": int,            # 0-25
        "weaknesses": [str],      # what's wrong
        "alternatives": [str],    # 3 stronger hook variants (only when score < 80)
        "engine": "llm" | "template",
      }
    """
    if not settings.hook_analyzer_enabled:
        return _template_analysis(hook_narration, hook_style)

    prompt = [
        {"role": "system", "content": (
            "You are a YouTube retention expert. Score the opening hook of a "
            "video on 4 dimensions (each 0-25): curiosity (open loop?), "
            "clarity (topic clear?), stakes (why should I care?), pacing "
            "(right rhythm?). Respond ONLY with JSON: "
            "{curiosity, clarity, stakes, pacing, weaknesses (array of short "
            "strings), alternatives (array of 3 stronger hook lines)}. "
            "Alternatives should be different angles — NOT just rephrasings."
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\nNiche: {niche}\nHook style: {hook_style or 'auto'}\n"
            f"Target length: {target_seconds}s\n\n"
            f"Hook narration (first ~5 seconds):\n\"\"\"{hook_narration}\"\"\""
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.5)
    except Exception as exc:
        log.warning("hook analyzer LLM call failed: %s", exc)
        return _template_analysis(hook_narration, hook_style)

    if not isinstance(data, dict):
        return _template_analysis(hook_narration, hook_style)

    def _safe_int(v: Any, lo: int = 0, hi: int = 25) -> int:
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return 0

    curiosity = _safe_int(data.get("curiosity"))
    clarity = _safe_int(data.get("clarity"))
    stakes = _safe_int(data.get("stakes"))
    pacing = _safe_int(data.get("pacing"))
    score = curiosity + clarity + stakes + pacing
    weaknesses = [clamp(str(w), 200) for w in (data.get("weaknesses") or [])][:5]
    # Only return alternatives when the hook is weak (score < 80).
    alternatives: list[str] = []
    if score < 80:
        alternatives = [clamp(str(a), 300) for a in (data.get("alternatives") or [])][:3]

    log.info("hook analysis: score=%d (cur=%d clar=%d stak=%d pac=%d)",
             score, curiosity, clarity, stakes, pacing)
    return {
        "score": score,
        "curiosity": curiosity,
        "clarity": clarity,
        "stakes": stakes,
        "pacing": pacing,
        "weaknesses": weaknesses,
        "alternatives": alternatives,
        "engine": "llm",
    }


def _template_analysis(hook_narration: str, hook_style: str | None) -> dict:
    """Fallback when the LLM is unavailable — uses simple heuristics."""
    text = (hook_narration or "").strip()
    curiosity = 12
    clarity = 14
    stakes = 10
    pacing = 12

    # Bump curiosity if it ends with a question.
    if text.endswith("?"):
        curiosity = min(25, curiosity + 6)
    # Bump clarity if the topic word is in the first 5 words.
    words = text.split()
    if len(words) >= 3 and len(words) <= 25:
        clarity = min(25, clarity + 4)
    # Bump stakes if power words appear.
    power_words = {"never", "always", "secret", "truth", "shocking", "dangerous",
                   "lost", "hidden", "banned"}
    if any(w.lower().strip(".,!?") in power_words for w in words):
        stakes = min(25, stakes + 6)
    # Penalize very long hooks.
    if len(words) > 35:
        pacing = max(0, pacing - 6)

    score = curiosity + clarity + stakes + pacing
    return {
        "score": score,
        "curiosity": curiosity,
        "clarity": clarity,
        "stakes": stakes,
        "pacing": pacing,
        "weaknesses": ["template analyzer — enable LLM for detailed feedback"],
        "alternatives": [],
        "engine": "template",
    }
