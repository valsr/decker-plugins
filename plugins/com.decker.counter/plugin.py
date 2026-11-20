"""Counter action: press adds step, double press adds double_step (if set), long press resets.

Settings (always complete: the server fills defaults from the manifest schema):
    step              int, added on press (default 1)
    double_step       int or empty, added on double press; empty means no double press, so presses
                      register immediately (default empty)
    max               int, wraps to 0 when reached; 0 = no limit (default 0)

Appearance (background, title) is drawn by Decker; the plugin only renders the count on a transparent
background.
"""

import io
import logging
from typing import Any

from decker_plugin_sdk import CardContext, DeckerPlugin, Gesture, card
from PIL import Image, ImageDraw, ImageFont

try:
    from decker_plugin_sdk.fonts import font_path
except ImportError:  # older Decker

    def font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None:
        return None


_KEY_SIZE = 72  # sizes in settings are relative to a 72 px key
_SCALE = 2  # render at 2x so the image stays sharp when scaled to larger keys
_COUNT_SIZE = 28
_COUNT_COLOR = "#ffffff"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = font_path(bold=True)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError as exc:
            logging.debug("cannot open %s: %s", path, exc)
    return ImageFont.load_default(size)


def render(count: int) -> bytes:
    """Render the count, centred, on a transparent background."""
    size = _KEY_SIZE * _SCALE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    centre = size // 2
    ImageDraw.Draw(img).text(
        (centre, centre),
        str(count),
        fill=_COUNT_COLOR,
        font=_font(_COUNT_SIZE * _SCALE),
        anchor="mm",
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@card("com.decker.counter.counter")
class CounterCard(DeckerPlugin):
    """Counts presses: press adds step, double press adds double_step, long press resets to 0."""

    def __init__(self) -> None:
        self._count: int = 0

    def gestures(self, settings: dict[str, Any]) -> frozenset[Gesture]:
        """Double press is only registered when double_step is set, so plain presses never wait for it."""
        wanted = {Gesture.PRESS, Gesture.LONG_PRESS}
        if settings.get("double_step") is not None:
            wanted.add(Gesture.DOUBLE_PRESS)
        return frozenset(wanted)

    def on_will_appear(self, ctx: CardContext) -> None:
        self._count = 0
        self._push(ctx)

    def on_press(self, ctx: CardContext) -> None:
        self._advance(ctx.settings["step"], ctx.settings["max"])
        self._push(ctx)

    def on_double_press(self, ctx: CardContext) -> None:
        self._advance(ctx.settings["double_step"] or 0, ctx.settings["max"])
        self._push(ctx)

    def on_long_press(self, ctx: CardContext) -> None:
        self._count = 0
        self._push(ctx)

    def on_settings_changed(self, ctx: CardContext) -> None:
        self._push(ctx)

    def _advance(self, amount: int, max_count: int) -> None:
        self._count += amount
        if max_count > 0 and self._count >= max_count:
            self._count = 0

    def _push(self, ctx: CardContext) -> None:
        ctx.set_image(render(self._count))
