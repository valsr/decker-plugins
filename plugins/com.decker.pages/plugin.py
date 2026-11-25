"""Pages plugin: next, previous and go-to-page actions."""

from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardProxy, action


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
