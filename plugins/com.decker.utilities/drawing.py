"""Drawing helpers for the brightness cards: the level-to-grey tint, a tinted icon and a caption."""

import io
import logging
from typing import Literal

from PIL import Image, ImageColor, ImageDraw, ImageFont

try:
    from decker_plugin_sdk.fonts import font_path
except ImportError:  # older Decker

    def font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None:
        return None


_KEY_SIZE = 72  # font sizes are relative to a 72 px key
_ICON_SHARE = 0.6
_CAPTION_SIZE = 16
_CAPTION_COLOR = "#ffffff"
_CAPTION_BOTTOM = 6
_LOW_FRACTION = 0.2  # a bicolor progress switches to its second colour at or below this share left
_RING_MARGIN = 2
_BAR_MARGIN = 8
_TIME_SIZE = 24
_TIME_WIDTH_SHARE = 0.8
_MIN_TIME_SIZE = 6


def level_grey(percent: int) -> str:
    """Grey for a brightness level: 0 is ``#000000``, 100 is ``#ffffff``, linear in between."""
    value = round(255 * max(0, min(100, percent)) / 100)
    return f"#{value:02x}{value:02x}{value:02x}"


def draw_icon(img: Image.Image, icon_png: bytes, color: str) -> None:
    """Paste the icon, filled with ``color`` where it is opaque, centred at about 60% of the key."""
    rgb = ImageColor.getrgb(color)[:3]
    icon = Image.open(io.BytesIO(icon_png)).convert("RGBA")
    side = round(min(img.size) * _ICON_SHARE)
    icon.thumbnail((side, side), Image.Resampling.LANCZOS)
    tinted = Image.new("RGBA", icon.size, (*rgb, 255))
    tinted.putalpha(icon.getchannel("A"))
    img.alpha_composite(tinted, ((img.width - icon.width) // 2, (img.height - icon.height) // 2))


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = font_path(bold=True)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError as exc:
            logging.debug("cannot open %s: %s", path, exc)
    return ImageFont.load_default(size)


def draw_caption(img: Image.Image, text: str) -> None:
    """Write ``text`` centred along the bottom of the key."""
    if not text:
        return
    scale = img.width / _KEY_SIZE
    ImageDraw.Draw(img).text(
        (img.width // 2, img.height - round(_CAPTION_BOTTOM * scale)),
        text,
        fill=_CAPTION_COLOR,
        font=_font(round(_CAPTION_SIZE * scale)),
        anchor="ms",
    )


def progress_color(mode: Literal["solid", "bicolor", "gradient"], c1: str, c2: str, fraction_left: float) -> str:
    """The progress colour: `c1`; bicolor uses `c2` at 20% left or less; gradient blends `c1` to `c2` by elapsed."""
    left = max(0.0, min(1.0, fraction_left))
    if mode == "solid" or (mode == "bicolor" and left > _LOW_FRACTION):
        return c1
    if mode == "bicolor":
        return c2
    first, second = ImageColor.getrgb(c1)[:3], ImageColor.getrgb(c2)[:3]
    mixed = (round(a + (b - a) * (1 - left)) for a, b in zip(first, second, strict=True))
    return "#" + "".join(f"{v:02x}" for v in mixed)


def draw_progress(
    img: Image.Image, kind: Literal["circle", "bar"], fraction_left: float, color: str, width: int
) -> None:
    """Draw what is left of the timer: a ring clockwise from 12 o'clock, or a bar from the left along the bottom.

    ``width`` is the line thickness for a 72 px key and scales with the image.
    """
    left = max(0.0, min(1.0, fraction_left))
    if left <= 0:
        return
    scale = img.width / _KEY_SIZE
    thickness = max(1, round(width * scale))
    draw = ImageDraw.Draw(img)
    if kind == "circle":
        edge = round(_RING_MARGIN * scale)
        box = (edge, edge, img.width - 1 - edge, img.height - 1 - edge)
        if left >= 1:
            draw.ellipse(box, outline=color, width=thickness)
        else:
            draw.arc(box, -90, -90 + 360 * left, fill=color, width=thickness)
        return
    margin = round(_BAR_MARGIN * scale)
    length = round((img.width - 2 * margin) * left)
    bottom = img.height - margin
    if length > 0:
        draw.rectangle((margin, bottom - thickness, margin + length - 1, bottom - 1), fill=color)


def draw_time(img: Image.Image, text: str) -> None:
    """Write ``text`` centred on the key, shrunk until it fits within 80% of the width."""
    if not text:
        return
    scale = img.width / _KEY_SIZE
    draw = ImageDraw.Draw(img)
    size = round(_TIME_SIZE * scale)
    font = _font(size)
    while size > _MIN_TIME_SIZE and draw.textlength(text, font=font) > img.width * _TIME_WIDTH_SHARE:
        size -= 2
        font = _font(size)
    draw.text((img.width // 2, img.height // 2), text, fill=_CAPTION_COLOR, font=font, anchor="mm")
