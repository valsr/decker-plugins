"""Pages plugin: next, previous and go-to-page actions, and the cards that bind them.

Next and Previous draw the plugin's own Font Awesome caret (``assets/``), recoloured and centred at about 60% of the
key. The caret SVGs use ``currentColor``, which renders black, so the chosen colour is substituted into the SVG.
"""

import re
from pathlib import Path
from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardContext, CardProxy, DeckerPlugin, action, card

_ASSETS = Path(__file__).parent / "assets"
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_DEFAULT_COLOUR = "#ffffff"
_CARET_SHARE = 0.6
_ROOT = re.compile(r"<svg\b[^>]*>")
_VIEWBOX = re.compile(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)\s*"')


def render_caret(svg: bytes, color: Any, ink: tuple[float, float, float, float] | None = None) -> bytes:
    """Recolour a ``currentColor`` SVG and centre it in a square viewBox so it fills about 60% of the key.

    ``ink`` is the drawn area (x0, y0, x1, y1) in viewBox units; it defaults to the whole viewBox. Font Awesome's
    carets sit in a tall 256x512 box with empty margins, so their ink box is passed in.
    """
    colour = color if isinstance(color, str) and _COLOUR.match(color) else _DEFAULT_COLOUR
    alpha = int(colour[7:9], 16) / 255 if len(colour) == 9 else 1.0
    text = svg.decode("utf-8")
    root = _ROOT.search(text)
    if root is None:
        return svg
    head, tail = root.group(0), text[root.end() :]
    match = _VIEWBOX.search(head)
    if match is not None:
        x, y, width, height = (float(g) for g in match.groups())
        x0, y0, x1, y1 = ink if ink is not None else (x, y, x + width, y + height)
        side = max(x1 - x0, y1 - y0) / _CARET_SHARE
        box = f'viewBox="{(x0 + x1 - side) / 2:g} {(y0 + y1 - side) / 2:g} {side:g} {side:g}"'
        head = head.replace(match.group(0), box)
    if alpha < 1.0:
        head = head[:-1] + f' opacity="{alpha:.3f}">'
    return (text[: root.start()] + head + tail.replace("currentColor", colour[:7])).encode("utf-8")


class ArrowCard(DeckerPlugin):
    """Shared behaviour of the Next and Previous keys: they draw the caret; their press binding does the rest."""

    asset = "caret-right.svg"
    ink: tuple[float, float, float, float] = (64, 96, 256, 416)

    def on_will_appear(self, ctx: CardContext) -> None:
        self._draw(ctx)

    def on_settings_changed(self, ctx: CardContext) -> None:
        self._draw(ctx)

    def _draw(self, ctx: CardContext) -> None:
        svg = (_ASSETS / self.asset).read_bytes()
        ctx.set_image(render_caret(svg, ctx.settings.get("color"), self.ink), "svg")


@card("com.decker.pages.next")
class NextCard(ArrowCard):
    """Next page key."""

    asset = "caret-right.svg"


@card("com.decker.pages.previous")
class PreviousCard(ArrowCard):
    """Previous page key."""

    asset = "caret-left.svg"
    ink = (0, 95, 193, 416)


def _needs_card(ctx: ActionCallContext) -> CardProxy:
    if ctx.card is None:
        raise ActionError("needs a card")
    return ctx.card


@action("com.decker.pages.next")
def next_page(ctx: ActionCallContext) -> None:
    """Switch the card's device to its next page."""
    _needs_card(ctx).switch_page("next", wrap=ctx.args.get("wrap") is True)


@action("com.decker.pages.previous")
def previous_page(ctx: ActionCallContext) -> None:
    """Switch the card's device to its previous page."""
    _needs_card(ctx).switch_page("previous", wrap=ctx.args.get("wrap") is True)


def _chosen_page(value: Any) -> tuple[str, str]:
    """(page id, page name) of a ``page`` value, or ("", "") for none, a deleted page or garbage."""
    if not isinstance(value, dict):
        return "", ""
    page_id, name = value.get("page_id"), value.get("name")
    if not isinstance(page_id, str) or not page_id:
        return "", ""
    return page_id, name if isinstance(name, str) else ""


@action("com.decker.pages.goto")
def goto(ctx: ActionCallContext) -> None:
    """Go to the chosen page; a missing page does nothing."""
    proxy = _needs_card(ctx)
    page_id, _name = _chosen_page(ctx.args.get("page"))
    if page_id:
        proxy.go_to_page(page_id)


def _press_page(bindings: Any) -> tuple[str, str]:
    press = bindings.get("press") if isinstance(bindings, dict) else None
    if not isinstance(press, dict) or press.get("action") != "com.decker.pages.goto":
        return "", ""
    args = press.get("args")
    return _chosen_page(args.get("page") if isinstance(args, dict) else None)


@card("com.decker.pages.goto")
class GotoCard(DeckerPlugin):
    """Titled "Go To <page name>" after the page its press binding goes to."""

    def on_will_appear(self, ctx: CardContext) -> None:
        self._title(ctx)

    def on_settings_changed(self, ctx: CardContext) -> None:
        self._title(ctx)

    @staticmethod
    def _title(ctx: CardContext) -> None:
        page_id, name = _press_page(ctx.bindings)
        ctx.set_title(f"Go To {name}" if page_id and name else "")
