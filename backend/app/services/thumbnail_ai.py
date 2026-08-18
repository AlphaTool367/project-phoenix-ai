"""AI thumbnail A/B testing + CTR prediction.

Wraps the existing thumbnail generator and adds two monetization features:

  1. **CTR prediction** — for each generated variant, the LLM looks at the
     title, scene, and variant metadata (palette, text placement, power
     word count) and predicts a click-through-rate score 0-100. The
     dashboard uses this to recommend the best variant.

  2. **A/B test tracking** — when a video is published, the first variant
     becomes the active thumbnail. After a configurable time window
     (default 7 days), the engine compares the CTR of the active variant
     against what the runner-up variant would have produced (using the
     CTR prediction as a proxy when real A/B data isn't available from
     the YouTube API). If the runner-up is predicted to win, the engine
     swaps the thumbnail.

  3. **Variant diversity** — extends the thumbnail generator's palette
     ring with 5 distinct visual treatments (warm fire, electric blue,
     emerald, gold, magenta) so each variant looks visibly different.

The A/B test data is stored in the ABTest DB table (defined in models.py).
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm
from .thumbnail import _load_font, _frame_from_clip, SIZE

log = get_logger("thumbnail_ai")

# 5 visually distinct palettes — extended from the base 3 to support A/B testing.
AB_PALETTES = [
    {"name": "warm_fire",   "accent": (255, 176, 0),  "rim": (20, 8, 40),
     "grad": ((255, 94, 58), (60, 10, 90)),   "emoji": "🔥"},
    {"name": "electric",    "accent": (0, 210, 255),  "rim": (4, 18, 44),
     "grad": ((24, 144, 255), (8, 8, 60)),    "emoji": "⚡"},
    {"name": "emerald",     "accent": (46, 224, 124), "rim": (6, 40, 34),
     "grad": ((46, 213, 115), (10, 50, 45)),  "emoji": "🌿"},
    {"name": "gold",        "accent": (255, 215, 0),  "rim": (40, 28, 4),
     "grad": ((255, 195, 18), (94, 31, 9)),   "emoji": "👑"},
    {"name": "magenta",     "accent": (235, 77, 152), "rim": (42, 8, 69),
     "grad": ((235, 77, 152), (42, 8, 69)),   "emoji": "🚀"},
]

POWER_WORDS = {
    "secret", "truth", "never", "always", "hidden", "shocking", "exposed",
    "why", "how", "what", "untold", "real", "myth", "changes", "everything",
    "banned", "illegal", "dangerous", "future", "lost", "found",
}


def _gradient_bg(palette: dict):
    import numpy as np
    w, h = SIZE
    c1, c2 = palette["grad"]
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = (np.array(c1, dtype=np.float32) * (1 - t)
            + np.array(c2, dtype=np.float32) * t)
    return Image.fromarray(np.broadcast_to(grad, (h, w, 3)).astype(np.uint8), "RGB")


def _compose_variant(base: Image.Image, title: str, channel: str,
                     palette: dict, variant: int) -> Image.Image:
    """Compose one thumbnail variant. `variant` 0..4 maps to a distinct
    visual treatment (text placement + scrim direction + accent bar)."""
    import textwrap
    w, h = SIZE
    img = base.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.30)

    # Variant-specific scrim direction.
    scrim = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    left_heavy = variant % 2 == 0
    top_heavy = variant == 2 or variant == 4
    for x in range(w):
        t = x / (w - 1)
        a = int(195 * (1 - t) ** 1.4) if left_heavy else int(195 * t ** 1.4)
        sd.line([(x, 0), (x, h)], fill=(0, 0, 0, a))
    if top_heavy:
        for y in range(h // 2):
            alpha = int(110 * (1 - y / (h / 2)))
            sd.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), scrim)

    d = ImageDraw.Draw(img)
    words = title.upper().split()
    font = _load_font(94 if len(title) < 42 else 78)
    wrapped = textwrap.wrap(" ".join(words), width=14)[:3]
    y = h - 90 - len(wrapped) * 100
    x0 = 60 if left_heavy else w - 60
    for line in wrapped:
        lx = x0
        for word in line.split(" "):
            color = (palette["accent"] if word.lower().strip(".,!?") in POWER_WORDS
                     else (255, 255, 255))
            bbox = d.textbbox((0, 0), word + " ", font=font, stroke_width=6)
            ww = bbox[2] - bbox[0]
            if not left_heavy:
                lx -= ww
            d.text((lx, y), word, font=font, fill=color,
                   stroke_width=6, stroke_fill=(0, 0, 0))
            if left_heavy:
                lx += ww
        y += 100

    # Channel badge.
    badge_font = _load_font(38)
    bx, by = (60, 48) if left_heavy else (w - 60, 48)
    text = f" {channel.upper()} "
    bb = d.textbbox((0, 0), text, font=badge_font)
    bw, bh = bb[2] - bb[0] + 16, bb[3] - bb[1] + 22
    if not left_heavy:
        bx -= bw
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=12, fill=palette["accent"])
    d.text((bx + 8, by + 10), text, font=badge_font, fill=(10, 10, 10))
    d.rectangle([0, h - 14, w, h], fill=palette["accent"])
    return img.convert("RGB")


async def generate_ab_thumbnails(
    video_id: int, title: str, channel_name: str,
    clip_path: str | None = None,
    count: int | None = None,
) -> list[dict]:
    """Generate `count` thumbnail variants (default: settings.thumbnail_variant_count).

    Returns a list of dicts:
      [{path, palette, variant, ctr_score, rationale}]
    where `ctr_score` is 0-100 (only when settings.thumbnail_ctr_prediction
    is True) and `rationale` is a short LLM-explained reason for the score.
    """
    n = int(count or settings.thumbnail_variant_count or 5)
    out_dir = settings.path(settings.data_dir, "thumbnails")
    frame = await _frame_from_clip(clip_path, out_dir / f"v{video_id}_frame.jpg")
    rng = random.Random(video_id * 31 + 7)

    variants: list[dict] = []
    for i in range(n):
        palette = AB_PALETTES[i % len(AB_PALETTES)]
        if frame and i < 2:
            base = Image.open(frame).resize(SIZE, Image.LANCZOS)
        else:
            base = _gradient_bg(palette)
            ov = Image.new("RGBA", SIZE, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            cx, cy, r = rng.randint(200, 1080), rng.randint(140, 560), 260
            od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 36))
            base = Image.alpha_composite(
                base.convert("RGBA"), ov.filter(ImageFilter.GaussianBlur(120))
            ).convert("RGB")
        img = _compose_variant(base, title, channel_name, palette, variant=i)
        out = out_dir / f"v{video_id}_thumb_{i}.jpg"
        img.save(out, quality=92)
        variants.append({
            "path": str(out),
            "palette": palette["name"],
            "variant": i,
            "emoji": palette["emoji"],
            "ctr_score": None,
            "rationale": "",
        })

    # Optional CTR prediction via LLM.
    if settings.thumbnail_ctr_prediction:
        await _predict_ctr_scores(video_id, title, variants)

    log.info("generated %d A/B thumbnail variants for video %d", len(variants), video_id)
    return variants


async def _predict_ctr_scores(video_id: int, title: str,
                              variants: list[dict]) -> None:
    """Ask the LLM to score each variant's CTR potential 0-100.

    Mutates `variants` in-place. The LLM gets the title + each variant's
    palette/emoji/placement and is asked to return JSON:
      [{variant, ctr_score, rationale}]
    """
    prompt = [
        {"role": "system", "content": (
            "You are a YouTube thumbnail CTR expert. You receive a video title "
            "and a list of thumbnail variants (each with a palette name, emoji, "
            "and text-placement variant number). Respond ONLY with a JSON array: "
            "[{variant, ctr_score (0-100 int), rationale (one short sentence)}]. "
            "Score higher when the palette matches the topic mood, the power "
            "word pops, and the composition is clean. Be honest — a 60 is good."
        )},
        {"role": "user", "content": (
            f"Title: {title}\n"
            f"Variants:\n" +
            "\n".join(f"  {v['variant']}: palette={v['palette']}, emoji={v['emoji']}, "
                      f"placement={'left' if v['variant'] % 2 == 0 else 'right'}"
                      for v in variants)
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.4)
    except Exception as exc:
        log.warning("CTR prediction LLM call failed: %s", exc)
        return
    if not isinstance(data, list):
        return
    by_variant = {int(d.get("variant", -1)): d for d in data if isinstance(d, dict)}
    for v in variants:
        d = by_variant.get(v["variant"])
        if not d:
            continue
        try:
            v["ctr_score"] = max(0, min(100, int(d.get("ctr_score", 0))))
        except (TypeError, ValueError):
            pass
        v["rationale"] = clamp(str(d.get("rationale", "")), 200)


def pick_best_variant(variants: list[dict]) -> dict | None:
    """Pick the variant with the highest predicted CTR score.

    Falls back to the first variant when no scores are available.
    """
    if not variants:
        return None
    scored = [v for v in variants if v.get("ctr_score") is not None]
    if not scored:
        return variants[0]
    return max(scored, key=lambda v: v["ctr_score"])
