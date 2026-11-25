"""The manifest parses with Decker's own loader and declares what the plugin promises."""

from pathlib import Path

from assertpy import assert_that
from decker.plugin.icons import read_icon
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import validate_settings

_DIR = Path(__file__).parents[1]
_MANIFEST = PluginManifest.load(_DIR / "manifest.json")


def test_identity_and_version_constraints():
    assert_that(_MANIFEST.id).is_equal_to("com.decker.utilities")
    assert_that(_MANIFEST.format).is_equal_to(3)
    assert_that(_MANIFEST.version).is_equal_to("2.1.1")
    assert_that(_MANIFEST.decker).is_equal_to(">=0.8.1")
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


_NOTHING = "com.decker.core.nothing"
_PRESETS = {
    "preset-brightness-up": ("Brightness Up", "brightness", {"mode": "increase", "value": 10}, "fas:sun"),
    "preset-brightness-down": ("Brightness Down", "brightness", {"mode": "decrease", "value": 10}, "fas:sun"),
    "preset-deck-brightness-up": ("Deck Brightness Up", "deck-brightness", {"mode": "increase", "value": 10}, "fas:tv"),
    "preset-deck-brightness-down": (
        "Deck Brightness Down",
        "deck-brightness",
        {"mode": "decrease", "value": 10},
        "fas:tv",
    ),
    "preset-lock": ("Lock screen", "lock", {}, "fas:lock"),
}


def test_presets_are_declared_and_bound() -> None:
    by_id = {p.id: p for p in _MANIFEST.presets}
    actions = {a.id: a for a in _MANIFEST.actions}

    assert_that(set(by_id)).is_equal_to({f"com.decker.utilities.{k}" for k in _PRESETS})
    for key, (name, action, args, icon) in _PRESETS.items():
        preset = by_id[f"com.decker.utilities.{key}"]
        press = preset.bindings["press"]
        action_id = f"com.decker.utilities.{action}"
        assert_that(preset.name).is_equal_to(name)
        assert_that(preset.icon).is_equal_to(icon)
        assert_that(press.action).is_equal_to(action_id)
        assert_that(dict(press.args)).is_equal_to(args)
        assert_that(actions[action_id].scope).is_equal_to("global")
        assert_that(validate_settings(actions[action_id].settings, press.args)).is_empty()
        assert_that(preset.appearance["icon"]).is_equal_to({"ref": icon, "color": "#ffffff"})
        assert_that(set(preset.bindings)).is_subset_of({"press", "double_press", "long_press"})


def test_no_sleep_preset() -> None:
    for preset in _MANIFEST.presets:
        assert_that(preset.id).does_not_contain("sleep")
        assert_that({b.action for b in preset.bindings.values()}).does_not_contain(
            "com.decker.utilities.sleep", "com.decker.utilities.sleep-cancel"
        )
    assert_that([p.id for p in _MANIFEST.presets]).does_not_contain_duplicates()


def test_actions_scopes_unchanged() -> None:
    scopes = {a.id.removeprefix("com.decker.utilities."): a.scope for a in _MANIFEST.actions}
    global_ids = {"brightness", "deck-brightness", "sleep", "lock", "sleep-cancel", "page", "profile"}

    assert_that({k for k, v in scopes.items() if v == "global"}).is_equal_to(global_ids)
    assert_that({k for k, v in scopes.items() if v == "plugin"}).is_equal_to(
        {
            "counter-increment",
            "counter-decrement",
            "counter-reset",
            "sleep-press",
            "sleep-after",
            "timer-toggle",
            "timer-reset",
            "stopwatch-toggle",
            "stopwatch-reset",
        }
    )


def test_cards_declare_their_actions() -> None:
    declared = {c.id.removeprefix("com.decker.utilities."): c.actions for c in _MANIFEST.cards}

    assert_that(declared).is_equal_to(
        {
            "counter": tuple(f"com.decker.utilities.counter-{a}" for a in ("increment", "decrement", "reset")),
            "sleep": ("com.decker.utilities.sleep-press", "com.decker.utilities.sleep-after"),
            "timer": ("com.decker.utilities.timer-toggle", "com.decker.utilities.timer-reset"),
            "stopwatch": ("com.decker.utilities.stopwatch-toggle", "com.decker.utilities.stopwatch-reset"),
            "brightness-level": (),
            "deck-brightness-level": (),
        }
    )


def test_every_plugin_action_is_claimed_by_a_card() -> None:
    claimed = [a for c in _MANIFEST.cards for a in c.actions]
    plugin_scoped = {a.id for a in _MANIFEST.actions if a.scope == "plugin"}

    assert_that(set(claimed)).is_equal_to(plugin_scoped)
    assert_that(claimed).does_not_contain_duplicates()
