"""Content type templates — 8 different video formats.

Each format has its own LLM prompt + template fallback, so the user can
pick the format that best fits their topic:

  - tutorial: step-by-step how-to
  - listicle: Top 10 / Top 5 countdown
  - news: breaking news roundup
  - review: product/service review
  - comparison: X vs Y
  - myth_busting: "5 myths about X debunked"
  - q_and_a: answers to audience questions
  - vlog: personal/narrative style

The orchestrator passes `content_type` to the scriptwriter, which picks
the right prompt template. When the LLM is unavailable, the template
fallback produces a format-appropriate script.
"""
from __future__ import annotations

from ..core.logging import get_logger
from ..core.utils import clamp

log = get_logger("content_types")

CONTENT_TYPES = [
    "explainer",    # default (hook → setup → escalation → payoff → CTA)
    "tutorial",     # step-by-step how-to
    "listicle",     # Top N countdown
    "news",         # breaking news roundup
    "review",       # product/service review
    "comparison",   # X vs Y
    "myth_busting", # myths debunked
    "q_and_a",      # audience Q&A
    "vlog",         # personal narrative
]

_TYPE_GUIDES = {
    "explainer": {
        "system": "You are an elite YouTube scriptwriter who maximizes retention. Write an explainer video with hook → setup → escalation → payoff → CTA.",
        "template_beats": [
            ("hook", "What if everything you thought about {topic} was only half the story?"),
            ("setup", "Let's set the scene. {topic} — it sounds simple, but the details are fascinating."),
            ("context", "For years, experts treated this as settled. Then new evidence flipped everything."),
            ("escalation", "And here's where it gets wild: the deeper you look, the stranger it gets."),
            ("payoff", "So what's the real takeaway? The truth is more useful than the myth."),
            ("cta", "If this changed how you see things, subscribe for more."),
        ],
    },
    "tutorial": {
        "system": "You are a YouTube tutorial expert. Write a step-by-step how-to video. Each scene is ONE step with a clear action verb. End with a 'try it yourself' CTA.",
        "template_beats": [
            ("hook", "Want to master {topic}? I'll walk you through it step by step."),
            ("step_1", "Step 1: Start with the basics. {topic} begins with understanding the core concept."),
            ("step_2", "Step 2: Set up your environment. Here's what you need before you begin."),
            ("step_3", "Step 3: The main technique. This is where most people get stuck — here's the fix."),
            ("step_4", "Step 4: Common mistakes to avoid. Skip this and you'll waste hours."),
            ("result", "Here's your final result. If it worked, subscribe for more tutorials."),
        ],
    },
    "listicle": {
        "system": "You are a YouTube listicle expert. Write a 'Top N' countdown video. Each scene is ONE item, starting from the least important and building to #1. Create curiosity between items.",
        "template_beats": [
            ("intro", "These are the top 5 things about {topic} that will change how you think."),
            ("item_5", "Number 5: The one everyone overlooks — but shouldn't."),
            ("item_4", "Number 4: This surprised even the experts."),
            ("item_3", "Number 3: The game-changer most people miss."),
            ("item_2", "Number 2: Almost #1, but not quite."),
            ("item_1", "And Number 1: The most important thing about {topic}. Subscribe for more lists."),
        ],
    },
    "news": {
        "system": "You are a YouTube news anchor. Write a breaking news roundup about {topic}. Be factual, urgent, and balanced. Cover what happened, why it matters, and what's next.",
        "template_beats": [
            ("breaking", "Breaking: {topic} just made headlines. Here's what you need to know."),
            ("what_happened", "Here's what actually happened, in plain terms."),
            ("why_it_matters", "Why does this matter? Because it affects you directly."),
            ("context", "For context, this isn't the first time we've seen something like this."),
            ("what_next", "So what happens next? Here's what to watch for."),
            ("cta", "Stay informed — subscribe for daily news roundups."),
        ],
    },
    "review": {
        "system": "You are a YouTube product reviewer. Write an honest review of {topic}. Cover: first impression, key features, pros, cons, and final verdict. Be balanced — not everything is perfect.",
        "template_beats": [
            ("first_impression", "So I got my hands on {topic}. Here's my honest first impression."),
            ("features", "Let's break down the key features that actually matter."),
            ("pros", "Here's what I loved about it — the stuff that genuinely impressed me."),
            ("cons", "But it's not perfect. Here are the things that frustrated me."),
            ("verdict", "So should you get it? Here's my final verdict."),
            ("cta", "If this review helped, smash subscribe for more honest reviews."),
        ],
    },
    "comparison": {
        "system": "You are a YouTube comparison expert. Write an X vs Y comparison about {topic}. Cover: what each option is, key differences, pros/cons of each, and a recommendation.",
        "template_beats": [
            ("intro", "{topic} — which side wins? Let's settle this once and for all."),
            ("option_a", "First, let's understand option A — its strengths and weaknesses."),
            ("option_b", "Now option B — and why it might be the better choice."),
            ("head_to_head", "Head to head: here's where they differ the most."),
            ("winner", "And the winner is... well, it depends. Here's my recommendation."),
            ("cta", "Which side are you on? Comment below and subscribe for more comparisons."),
        ],
    },
    "myth_busting": {
        "system": "You are a YouTube myth-buster. Write a 'myths debunked' video about {topic}. Each scene busts ONE myth: state the myth, then reveal the truth with evidence.",
        "template_beats": [
            ("intro", "Everything you know about {topic} might be wrong. Let's bust some myths."),
            ("myth_1", "Myth #1: 'It's too complicated.' Reality: it's simpler than you think."),
            ("myth_2", "Myth #2: 'You need special talent.' Reality: practice beats talent."),
            ("myth_3", "Myth #3: 'It's too late to start.' Reality: the best time is now."),
            ("truth", "Here's the real truth about {topic} that nobody tells you."),
            ("cta", "Busted a myth you believed? Subscribe for more truth bombs."),
        ],
    },
    "q_and_a": {
        "system": "You are a YouTube Q&A host. Write a Q&A video about {topic}. Each scene answers ONE audience question with a clear, helpful answer.",
        "template_beats": [
            ("intro", "You asked, I answer. Today's Q&A is all about {topic}."),
            ("q1", "First question: 'How do I get started?' Here's my advice."),
            ("q2", "Next: 'What's the biggest mistake beginners make?' Let me save you the pain."),
            ("q3", "Someone asked: 'How long until I see results?' Honest answer coming up."),
            ("q4", "Final question: 'Is it worth it?' Here's what I really think."),
            ("cta", "Got more questions? Drop them below and subscribe for the next Q&A."),
        ],
    },
    "vlog": {
        "system": "You are a YouTube vlogger. Write a personal, narrative-style vlog about {topic}. Use 'I' and 'you', share personal anecdotes, and create an emotional connection.",
        "template_beats": [
            ("hook", "So today I want to talk about something personal — {topic}."),
            ("story", "Let me tell you a story. A while back, I was struggling with this too."),
            ("realization", "And then it hit me. Here's what I realized about {topic}."),
            ("advice", "If you're going through the same thing, here's what I'd tell you."),
            ("reflection", "Looking back, I wish someone had told me this sooner."),
            ("cta", "If this resonated, subscribe — I share something personal every week."),
        ],
    },
}


def get_type_guide(content_type: str) -> dict:
    """Return the system prompt + template beats for a content type."""
    ct = (content_type or "explainer").lower().strip()
    if ct not in _TYPE_GUIDES:
        ct = "explainer"
    return _TYPE_GUIDES[ct]


def get_template_beats(content_type: str, topic: str) -> list[tuple[str, str, str]]:
    """Return template beats with narration + visual_query for a content type.

    Returns list of (beat_name, narration, visual_query).
    """
    guide = get_type_guide(content_type)
    beats_raw = guide["template_beats"]
    # Visual queries are diverse per beat.
    vqs = [
        "abstract concept cinematic dark",
        "close-up detail cinematic",
        "vintage archive footage",
        "dramatic lighting cinematic",
        "sunrise revelation cinematic",
        "city skyline night cinematic",
    ]
    out = []
    for i, (beat, narration) in enumerate(beats_raw):
        try:
            filled = narration.format(topic=topic.lower())
        except (KeyError, ValueError):
            filled = narration
        vq = vqs[i % len(vqs)]
        out.append((beat, filled, vq))
    return out
