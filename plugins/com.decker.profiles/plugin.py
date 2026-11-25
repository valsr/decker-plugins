"""Profiles plugin: next, previous and go-to-profile actions."""

from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardProxy, action


def _needs_card(ctx: ActionCallContext) -> CardProxy:
    if ctx.card is None:
        raise ActionError("needs a card")
    return ctx.card


@action("com.decker.profiles.next")
def next_profile(ctx: ActionCallContext) -> None:
    """Switch the card's device to its next profile."""
    _needs_card(ctx).switch_profile("next", wrap=ctx.args.get("wrap") is True)


@action("com.decker.profiles.previous")
def previous_profile(ctx: ActionCallContext) -> None:
    """Switch the card's device to its previous profile."""
    _needs_card(ctx).switch_profile("previous", wrap=ctx.args.get("wrap") is True)


def _chosen_profile(value: Any) -> tuple[int, str, str]:
    """(id, name, icon ref) of a ``profile`` value, or (-1, "", "") for none, a deleted profile or garbage."""
    if not isinstance(value, dict):
        return -1, "", ""
    profile_id, name, icon = value.get("profile_id"), value.get("name"), value.get("icon")
    if isinstance(profile_id, bool) or not isinstance(profile_id, int) or profile_id < 0:
        return -1, "", ""
    return profile_id, name if isinstance(name, str) else "", icon if isinstance(icon, str) else ""


@action("com.decker.profiles.goto")
def goto(ctx: ActionCallContext) -> None:
    """Go to the chosen profile; a missing profile does nothing."""
    proxy = _needs_card(ctx)
    profile_id, _name, _icon = _chosen_profile(ctx.args.get("profile"))
    if profile_id >= 0:
        proxy.go_to_profile(profile_id)
