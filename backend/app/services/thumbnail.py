"""AI thumbnail generator — 3 high-CTR variations per video (Pillow).

Composition: scene frame or gradient background -> contrast scrim ->
bold stroked headline with an accent-colored power word -> badge.
Fonts: drop any .ttf/.otf into assets/fonts/ (a heavy bold face works best);
falls back to DejaVu Sans Bold, then Pillow's default bitmap font.
"""
from __future__ import annotations

import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, run_cmd

log = get_logger("thumbnail")

SIZE = (1280, 720)
PALETTES = [
    {"accent": (255, 176, 0), "rim": (20, 8, 40), "grad": ((255, 94, 58), (60, 10, 90))},
    {"accent": (0, 210, 255), "rim": (4, 18, 44), "grad": ((24, 144, 255), (8, 8, 60))},
    {"accent": (46, 224, 124), "rim": (6, 40, 34), "grad": ((46, 213, 115), (10, 50, 45))},
]
POWER_WORDS = {
    "secret", "truth", "never", "always", "hidden", "shocking", "exposed",
    "why", "how", "what", "untold", "real", "myth", "changes", "everything",
}


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    fonts_dir = settings.assets_path / "fonts"
    if fonts_dir.exists():
        for f in sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf")):
            try:
                return ImageFont.truetype(str(f), px)
            except OSError:
                continue
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_bg(palette: dict) -> Image.Image:
    import numpy as np

    w, h = SIZE
    c1, c2 = palette["grad"]
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = (np.array(c1, dtype=np.float32) * (1 - t)
            + np.array(c2, dtype=np.float32) * t)
    return Image.fromarray(np.broadcast_to(grad, (h, w, 3)).astype(np.uint8), "RGB")


async def _frame_from_clip(clip_path: str | None, dest: Path) -> Path | None:
    if not clip_path or not Path(clip_path).exists():
        return None
    rc, _, _ = await run_cmd([
        ffmpeg_bin(), "-y", "-ss", "1.2", "-i", clip_path,
        "-frames:v", "1", "-q:v", "3", str(dest),
    ])
    return dest if rc == 0 and dest.exists() else None


def _compose(base: Image.Image, title: str, channel: str, palette: dict,
             variant: int) -> Image.Image:
    w, h = SIZE
    img = base.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Color(img).enhance(1.25)

    # contrast scrim (stronger on text side)
    scrim = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    left_heavy = variant % 2 == 0
    for x in range(w):
        t = x / (w - 1)
        a = int(185 * (1 - t) ** 1.4) if left_heavy else int(185 * t ** 1.4)
        sd.line([(x, 0), (x, h)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img.convert("RGBA"), scrim)

    d = ImageDraw.Draw(img)
    # headline
    words = title.upper().split()
    font = _load_font(92 if len(title) < 42 else 76)
    wrapped = textwrap.wrap(" ".join(words), width=14)[:3]
    y = h - 90 - len(wrapped) * 100
    x0 = 60 if left_heavy else w - 60
    for line in wrapped:
        lx = x0
        for word in line.split(" "):
            color = palette["accent"] if word.lower().strip(".,!?") in POWER_WORDS else (255, 255, 255)
            bbox = d.textbbox((0, 0), word + " ", font=font, stroke_width=6)
            ww = bbox[2] - bbox[0]
            if not left_heavy:
                lx -= ww
            d.text((lx, y), word, font=font, fill=color,
                   stroke_width=6, stroke_fill=(0, 0, 0))
            if left_heavy:
                lx += ww
        y += 100

    # accent bar + channel badge
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


async def generate_thumbnails(
    video_id: int, title: str, channel_name: str,
    clip_path: str | None = None, count: int = 3,
) -> list[str]:
    out_dir = settings.path(settings.data_dir, "thumbnails")
    frame = await _frame_from_clip(clip_path, out_dir / f"v{video_id}_frame.jpg")
    paths: list[str] = []
    rng = random.Random(video_id)

    for i in range(count):
        palette = PALETTES[i % len(PALETTES)]
        if frame and i < 2:
            base = Image.open(frame).resize(SIZE, Image.LANCZOS)
        else:
            base = _gradient_bg(palette)
            # soft light orb so generated thumbs don't look flat
            ov = Image.new("RGBA", SIZE, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            cx, cy, r = rng.randint(200, 1080), rng.randint(140, 560), 260
            od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 36))
            base = Image.alpha_composite(
                base.convert("RGBA"), ov.filter(ImageFilter.GaussianBlur(120))
            ).convert("RGB")
        img = _compose(base, title, channel_name, palette, variant=i)
        out = out_dir / f"v{video_id}_thumb_{i}.jpg"
        img.save(out, quality=92)
        paths.append(str(out))
    log.info("generated %d thumbnail variations for video %d", len(paths), video_id)
    return paths
