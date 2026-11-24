"""Drawing helpers for the brightness cards: the level-to-grey tint, a tinted icon and a caption."""

import io
import logging

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
