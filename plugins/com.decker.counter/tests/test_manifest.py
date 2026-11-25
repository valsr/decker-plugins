"""The manifest parses with Decker's own loader and declares what the plugin promises."""

from pathlib import Path

from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

_MANIFEST = PluginManifest.load(Path(__file__).parents[1] / "manifest.json")


def test_identity_and_version_constraints() -> None:
    assert_that(_MANIFEST.id).is_equal_to("com.decker.counter")
    assert_that(_MANIFEST.version).is_equal_to("2.0.2")
    assert_that(_MANIFEST.decker).is_equal_to(">=0.8.1")


def test_card_declares_its_actions() -> None:
    (card,) = _MANIFEST.cards

    assert_that(card.actions).is_equal_to(tuple(f"com.decker.counter.{a}" for a in ("increment", "decrement", "reset")))


def test_every_plugin_action_is_claimed_by_a_card() -> None:
    claimed = [a for c in _MANIFEST.cards for a in c.actions]

    assert_that(set(claimed)).is_equal_to({a.id for a in _MANIFEST.actions if a.scope == "plugin"})
    assert_that(claimed).does_not_contain_duplicates()
