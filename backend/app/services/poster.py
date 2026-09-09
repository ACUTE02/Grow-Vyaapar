"""Print the offer onto the generated poster.

Diffusion models are bad at text. Asking one to render "20% off toothpaste"
inside the picture gives warped, misspelled letters most of the time, and that
is a property of how the models work rather than something a better prompt
fixes. So the pipeline splits in two, the same way the copy pipeline already
splits between the model and a template:

    the generator  ->  a good-looking background, no text
    Pillow         ->  the words a customer actually has to read

Everything here is deliberately failure-tolerant. A poster is a nice-to-have on
a page that already works; if the background cannot be fetched or the font
cannot be loaded, the caller keeps the plain generated image rather than
showing a broken one.
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# backend/static/campaigns - served by the app at /static/campaigns.
BACKEND_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BACKEND_DIR / "static"
POSTER_DIR = STATIC_DIR / "campaigns"
FONT_DIR = BACKEND_DIR / "assets" / "fonts"

FETCH_TIMEOUT = 30.0
CANVAS = 1024


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """A bundled font if there is one, else Pillow's own scalable default.

    Drop any .ttf into backend/assets/fonts/ and it is picked up without a code
    change - which is how a Devanagari-capable face (Noto Sans Devanagari, say)
    would be added. Pillow's built-in default covers Latin only, so an offer
    typed in Hindi renders as empty boxes until such a file is present. Better
    to say that here than to have it discovered on a printed poster.
    """
    if FONT_DIR.is_dir():
        names = sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf"))
        preferred = [path for path in names if ("bold" in path.name.lower()) == bold]
        for path in preferred or names:
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                logger.warning("Could not load font %s", path)
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap measured against the real font, not a character count."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw, text: str, max_width: int, *, start: int, minimum: int, bold: bool
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrink until the text fits in at most two lines.

    A long offer at a fixed size either overflows the image or gets clipped;
    both look broken. Shrinking is the one behaviour that always produces
    something readable.
    """
    size = start
    while size > minimum:
        font = _font(size, bold=bold)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= 2:
            return font, lines
        size -= 4
    font = _font(minimum, bold=bold)
    return font, _wrap(draw, text, font, max_width)[:2]


def compose_poster(
    background_url: str,
    *,
    store_name: str,
    occasion: str,
    offer_text: str | None,
    address: str | None = None,
    key: str,
) -> str:
    """Draw the offer onto the background and return a URL for the result.

    `key` makes the filename stable per campaign, so regenerating replaces the
    file instead of leaving orphans behind. Returns a path relative to the API
    root (/static/campaigns/...), or `background_url` unchanged if anything at
    all goes wrong - a plain poster beats a broken one.
    """
    try:
        response = httpx.get(background_url, timeout=FETCH_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as exc:
        logger.warning("Poster background could not be fetched (%s): %s", background_url, exc)
        return background_url

    try:
        image = image.resize((CANVAS, CANVAS)) if image.size != (CANVAS, CANVAS) else image
        width, height = image.size
        margin = int(width * 0.06)
        max_text_width = width - margin * 2

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Measure everything before drawing anything: the bar has to be as tall
        # as the text it will hold, and the text position depends on the bar.
        blocks: list[tuple[ImageFont.FreeTypeFont, list[str], tuple[int, int, int], int]] = []

        if offer_text and offer_text.strip():
            font, lines = _fit(
                draw, offer_text.strip(), max_text_width, start=84, minimum=34, bold=True
            )
            blocks.append((font, lines, (255, 255, 255), 14))

        heading = f"{occasion.strip()} at {store_name}".strip()
        font, lines = _fit(draw, heading, max_text_width, start=46, minimum=26, bold=False)
        blocks.append((font, lines, (255, 236, 209), 8))

        if address and address.strip():
            font, lines = _fit(
                draw, address.strip(), max_text_width, start=30, minimum=20, bold=False
            )
            blocks.append((font, lines, (223, 214, 201), 0))

        line_gap = 6
        block_height = 0
        for font, lines, _colour, after in blocks:
            ascent, descent = font.getmetrics()
            block_height += len(lines) * (ascent + descent + line_gap) + after

        bar_padding = int(height * 0.045)
        bar_height = min(block_height + bar_padding * 2, int(height * 0.6))
        bar_top = height - bar_height

        # A gradient rather than a flat bar: the text end stays dark enough to
        # read on any background, and the top edge does not cut across the
        # picture as a hard line.
        for offset in range(bar_height):
            alpha = int(30 + (215 * (offset / max(1, bar_height - 1)) ** 0.75))
            draw.line(
                [(0, bar_top + offset), (width, bar_top + offset)],
                fill=(14, 12, 10, alpha),
            )

        cursor = bar_top + bar_padding
        for font, lines, colour, after in blocks:
            ascent, descent = font.getmetrics()
            for line in lines:
                draw.text((margin, cursor), line, font=font, fill=(*colour, 255))
                cursor += ascent + descent + line_gap
            cursor += after

        # A thin accent rule keyed to the marigold in the app's palette, so the
        # poster and the product look like they came from the same place.
        draw.rectangle(
            [(0, bar_top), (width, bar_top + 4)], fill=(217, 117, 40, 235)
        )

        composed = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

        POSTER_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        filename = f"{digest}.jpg"
        composed.save(POSTER_DIR / filename, format="JPEG", quality=88, optimize=True)
        return f"/static/campaigns/{filename}"
    except Exception as exc:
        logger.warning("Poster could not be composed: %s", exc)
        return background_url
