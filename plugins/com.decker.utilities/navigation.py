"""Page and Profile: global actions that move a device between pages or profiles, and the cards that bind them.

Each card's gestures bind to the global action with their own arguments; the card face follows the press binding:
the target page's name, the target profile's icon and name, or a caret for next and previous. The caret SVGs
(``assets/``, Font Awesome) use ``currentColor``, which renders black, so the chosen colour is substituted in.
"""

import re
from pathlib import Path
from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardContext, DeckerPlugin, action, card

PAGE = "com.decker.utilities.page"
PROFILE = "com.decker.utilities.profile"

_ASSETS = Path(__file__).parent / "assets"
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_DEFAULT_COLOUR = "#ffffff"
_CARET_SHARE = 0.6
_ROOT = re.compile(r"<svg\b[^>]*>")
_VIEWBOX = re.compile(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)\s*"')
_RIGHT_INK = (64.0, 96.0, 256.0, 416.0)  # the drawn area of Font Awesome's carets inside their 256x512 viewBox
_LEFT_INK = (0.0, 95.0, 193.0, 416.0)


def render_caret(svg: bytes, color: Any, ink: tuple[float, float, float, float] | None = None) -> bytes:
    """Recolour a ``currentColor`` SVG and centre it in a square viewBox so it fills about 60% of the key.

    ``ink`` is the drawn area (x0, y0, x1, y1) in viewBox units; it defaults to the whole viewBox.
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


def _live_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _page_target(value: Any) -> tuple[str, str] | None:
    """(page id, name) of a delivered ``page`` value, or None for unset, deleted (``profile_id`` -1) or garbage."""
    if not isinstance(value, dict) or not _live_id(value.get("profile_id")):
        return None
    page_id, name = value.get("page_id"), value.get("name")
    if not isinstance(page_id, str) or not page_id:
        return None
    return page_id, name if isinstance(name, str) else ""


def _profile_target(value: Any) -> tuple[int, str, str] | None:
    """(id, name, icon ref) of a delivered ``profile`` value, or None for unset, deleted (-1) or garbage."""
    if not isinstance(value, dict) or not _live_id(value.get("profile_id")):
        return None
    name, icon = value.get("name"), value.get("icon")
    return value["profile_id"], name if isinstance(name, str) else "", icon if isinstance(icon, str) else ""


def _wrap(ctx: ActionCallContext) -> bool:
    return ctx.args.get("wrap") is True


@action(PAGE)
def page(ctx: ActionCallContext) -> None:
    """Switch the device to the next or previous page, or to the chosen one; through the card if the call has one."""
    mode = ctx.args.get("mode", "next")
    nav = ctx.card or ctx
    if mode in ("next", "previous"):
        nav.switch_page(mode, wrap=_wrap(ctx))
    elif mode == "page":
        target = _page_target(ctx.args.get("page"))
        if target is None:
            raise ActionError("the chosen page no longer exists")
        nav.go_to_page(target[0])
    else:
        raise ActionError(f"unknown mode {mode!r}")


@action(PROFILE)
def profile(ctx: ActionCallContext) -> None:
    """Switch the device to the next or previous profile, or to the chosen one; through the card if there is one."""
    mode = ctx.args.get("mode", "next")
    nav = ctx.card or ctx
    if mode in ("next", "previous"):
        nav.switch_profile(mode, wrap=_wrap(ctx))
    elif mode == "profile":
        target = _profile_target(ctx.args.get("profile"))
        if target is None:
            raise ActionError("the chosen profile no longer exists")
        nav.go_to_profile(target[0])
    else:
        raise ActionError(f"unknown mode {mode!r}")


def _press_args(bindings: Any, action_id: str) -> dict[str, Any]:
    press = bindings.get("press") if isinstance(bindings, dict) else None
    if not isinstance(press, dict) or press.get("action") != action_id:
        return {}
    args = press.get("args")
    return args if isinstance(args, dict) else {}


class _NavigationCard(DeckerPlugin):
    """Draws what the press binding does; the binding itself does the navigating."""

    action_id = ""

    def on_will_appear(self, ctx: CardContext) -> None:
        self._show(ctx)

    def on_settings_changed(self, ctx: CardContext) -> None:
        self._show(ctx)

    def _show(self, ctx: CardContext) -> None:
        args = _press_args(ctx.bindings, self.action_id)
        mode = args.get("mode")
        if mode in ("next", "previous"):
            asset, ink = ("caret-right.svg", _RIGHT_INK) if mode == "next" else ("caret-left.svg", _LEFT_INK)
            ctx.set_image(render_caret((_ASSETS / asset).read_bytes(), ctx.settings.get("color"), ink), "svg")
            ctx.set_title("")
        else:
            self._show_target(ctx, args)

    def _show_target(self, ctx: CardContext, args: dict[str, Any]) -> None:
        ctx.clear_image()
        ctx.set_title("")


@card(PAGE)
class PageCard(_NavigationCard):
    """Next/previous caret, or the name of the page the press goes to."""

    action_id = PAGE

    def _show_target(self, ctx: CardContext, args: dict[str, Any]) -> None:
        target = _page_target(args.get("page")) if args.get("mode") == "page" else None
        ctx.clear_image()
        ctx.set_title(target[1] if target else "")


@card(PROFILE)
class ProfileCard(_NavigationCard):
    """Next/previous caret, or the icon and name of the profile the press goes to."""

    action_id = PROFILE

    def _show_target(self, ctx: CardContext, args: dict[str, Any]) -> None:
        target = _profile_target(args.get("profile")) if args.get("mode") == "profile" else None
        if target and target[2]:
            ctx.set_icon(target[2])
        else:
            ctx.clear_image()
        ctx.set_title(target[1] if target else "")
