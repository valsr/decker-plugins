"""Pages plugin: next, previous and go-to-page keys. The indicator and name presets are static actions."""

from decker_plugin_sdk import DeckerPlugin, action


@action("com.decker.pages.next")
class NextAction(DeckerPlugin):
    """Next page key."""


@action("com.decker.pages.previous")
class PreviousAction(DeckerPlugin):
    """Previous page key."""


@action("com.decker.pages.goto")
class GotoAction(DeckerPlugin):
    """Go to a chosen page."""
