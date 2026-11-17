"""Icon action: shows an icon from an installed icon pack on the key.

Settings (always complete: the server fills defaults from the manifest schema):
    icon   {"ref": "" or "pack:<pack id>/<path>", "color": "#rrggbb[aa]"}

The server reads the icon from its pack registry and fills SVG icons with the colour; the plugin only passes the
reference on. Background and title are drawn by Decker.
"""

from decker_plugin_sdk import ActionContext, DeckerPlugin, action


@action("com.decker.icon.icon")
class IconAction(DeckerPlugin):
    """Shows the chosen pack icon, or nothing when none is chosen."""

    def on_will_appear(self, ctx: ActionContext) -> None:
        self._show(ctx)

    def on_settings_changed(self, ctx: ActionContext) -> None:
        self._show(ctx)

    @staticmethod
    def _show(ctx: ActionContext) -> None:
        icon = ctx.settings.get("icon")
        ref = icon.get("ref", "") if isinstance(icon, dict) else ""
        if ref:
            ctx.set_icon(ref, icon.get("color"))
        else:
            ctx.clear_image()
