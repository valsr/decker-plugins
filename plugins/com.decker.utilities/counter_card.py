"""Counter: a card that shows a count, and plugin actions that change it.

The card's default bindings are press -> count up, double press -> count down, long press -> reset. The count
lives on the card instance; the actions reach it through ``ctx.card.instance``.

Card settings: ``max`` (int, the count wraps to 0 when it reaches it; 0 = no limit).
Action settings: ``step`` (int, default 1) for count up and count down.

Appearance (background, title) is drawn by Decker; the plugin only draws the count on a transparent background.
"""

import io
import logging

from decker_plugin_sdk import ActionCallContext, ActionError, CardContext, DeckerPlugin, OwnCardProxy, action, card
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


def _draw(img: Image.Image, count: int) -> None:
    scale = img.width / _KEY_SIZE
    ImageDraw.Draw(img).text(
        (img.width // 2, img.height // 2),
        str(count),
        fill=_COUNT_COLOR,
        font=_font(round(_COUNT_SIZE * scale)),
        anchor="mm",
    )


def render(count: int) -> bytes:
    """Render the count, centred, on a transparent background."""
    size = _KEY_SIZE * _SCALE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw(img, count)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@card("com.decker.utilities.counter")
class CounterCard(DeckerPlugin):
    """Shows a count; the Counter actions change it."""

    def __init__(self) -> None:
        self.count: int = 0

    def on_will_appear(self, ctx: CardContext) -> None:
        self.count = 0
        ctx.queue_paint()

    def on_settings_changed(self, ctx: CardContext) -> None:
        ctx.queue_paint()

    def on_paint(self, ctx: CardContext, img: Image.Image) -> None:  # pylint: disable=unused-argument
        img.paste((0, 0, 0, 0), (0, 0, *img.size))
        _draw(img, self.count)

    def advance(self, amount: int, max_count: int) -> None:
        """Add `amount` (may be negative); wrap to 0 at `max_count` when it is set."""
        self.count += amount
        if max_count > 0 and self.count >= max_count:
            self.count = 0


def _own_card(ctx: ActionCallContext) -> tuple[OwnCardProxy, CounterCard]:
    proxy = ctx.card
    if not isinstance(proxy, OwnCardProxy) or not isinstance(proxy.instance, CounterCard):
        raise ActionError("Counter actions need a card")
    return proxy, proxy.instance


def _step(ctx: ActionCallContext, sign: int) -> None:
    proxy, instance = _own_card(ctx)
    instance.advance(sign * int(ctx.args["step"]), int(proxy.settings.get("max", 0)))
    proxy.queue_paint()


@action("com.decker.utilities.counter-increment")
def increment(ctx: ActionCallContext) -> None:
    """Add the step to the card's count."""
    _step(ctx, 1)


@action("com.decker.utilities.counter-decrement")
def decrement(ctx: ActionCallContext) -> None:
    """Subtract the step from the card's count."""
    _step(ctx, -1)


@action("com.decker.utilities.counter-reset")
def reset(ctx: ActionCallContext) -> None:
    """Set the card's count to 0."""
    proxy, instance = _own_card(ctx)
    instance.count = 0
    proxy.queue_paint()
