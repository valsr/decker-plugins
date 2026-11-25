"""The manifest parses with Decker's own loader and declares what the plugin promises."""

from pathlib import Path

from assertpy import assert_that
from decker.plugin.icons import read_icon
from decker.plugin.manifest import PluginManifest

_DIR = Path(__file__).parents[1]
_MANIFEST = PluginManifest.load(_DIR / "manifest.json")


def test_identity_and_version_constraints():
    assert_that(_MANIFEST.id).is_equal_to("com.decker.utilities")
    assert_that(_MANIFEST.format).is_equal_to(3)
    assert_that(_MANIFEST.version).is_equal_to("1.0.0")
    assert_that(_MANIFEST.decker).is_equal_to(">=0.7.2")
    assert_that(_MANIFEST.category).is_equal_to("Utilities")
    assert_that(_MANIFEST.homepage).is_equal_to("https://github.com/valsr/decker-plugins")


def test_runs_on_all_platforms():
    assert_that(set(_MANIFEST.platforms.os or ())).is_equal_to({"linux", "windows", "macos"})


def test_runtime_requirements():
    assert_that(_MANIFEST.runtime.requirements).is_equal_to(
        (
            "pillow>=12",
            'screen-brightness-control; sys_platform != "darwin"',
            'jeepney; sys_platform == "linux"',
        )
    )


def test_declares_the_brightness_level_variable_so_the_plugin_stays_running():
    assert_that([v.name for v in _MANIFEST.variables]).contains("brightness_level")


def test_every_contribution_id_is_namespaced():
    ids = [c.id for c in (*_MANIFEST.cards, *_MANIFEST.actions, *_MANIFEST.icon_packs)]

    assert_that(ids).is_not_empty()
    assert_that(all(i.startswith("com.decker.utilities.") for i in ids)).is_true()


def test_every_icon_path_exists():
    icons = {_MANIFEST.icon, *(c.icon for c in _MANIFEST.cards), *(a.icon for a in _MANIFEST.actions)}

    for icon in icons - {None}:
        assert_that(read_icon(_DIR, icon)).described_as(icon).is_not_none()


def test_only_the_stateful_cards_are_shipped() -> None:
    kept = {"counter", "brightness-level", "deck-brightness-level", "sleep", "timer", "stopwatch"}

    assert_that({c.id for c in _MANIFEST.cards}).is_equal_to({f"com.decker.utilities.{k}" for k in kept})


def test_every_action_the_kept_cards_bind_still_exists() -> None:
    action_ids = {a.id for a in _MANIFEST.actions}
    bound = {
        b.action for c in _MANIFEST.cards for b in c.bindings.values() if b.action.startswith("com.decker.utilities.")
    }

    assert_that(bound).is_not_empty()
    assert_that(action_ids).contains(*bound)
    assert_that(action_ids).contains(
        "com.decker.utilities.page",
        "com.decker.utilities.profile",
        "com.decker.utilities.brightness",
        "com.decker.utilities.deck-brightness",
    )
