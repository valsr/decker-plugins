"""Page and Profile: global actions that move a device between pages or profiles.

They are reached from the Actions tab; there are no preset cards for them.
"""

from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, action

PAGE = "com.decker.utilities.page"
PROFILE = "com.decker.utilities.profile"


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
