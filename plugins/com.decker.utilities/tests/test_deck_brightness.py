"""Deck brightness action, cards and variables, through the SDK loop with a harness that plays the server."""

import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

sys.path.insert(0, str(Path(__file__).parent))
from _harness import DEVICE, PLUGIN_DIR, Harness, load_plugin  # noqa: E402
from deck_brightness import _decks  # noqa: E402

_ACTION = "com.decker.utilities.deck-brightness"
_LEVEL = "com.decker.utilities.deck-brightness-level"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _LEVEL, "DeckBrightnessLevelCard")
    harness.deck_levels[DEVICE] = 70
    yield harness
    harness.close()


def _wait_until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "condition did not settle"
        time.sleep(0.01)


def _run(key: Harness, with_card: bool = False, device: str = DEVICE, **args: Any) -> dict:
    return key.run_action(_ACTION, args, with_card=with_card, device=device)


def _sets(key: Harness) -> list[int]:
    return [s["percent"] for s in key.deck_sets]


# --- the action ---


def test_increase_adds_the_value_to_the_decks_level_and_sends_it(key: Harness) -> None:
    result = _run(key, mode="increase", value=10)

    assert_that(result).contains_entry({"ok": True}, {"value": 80})
    assert_that(key.deck_sets).is_equal_to([{"device": DEVICE, "percent": 80}])


def test_decrease_below_zero_sends_zero_and_the_server_clamps(key: Harness) -> None:
    key.deck_levels[DEVICE] = 5

    result = _run(key, mode="decrease", value=10)

    assert_that(result).contains_entry({"value": 0})
    assert_that(_sets(key)).is_equal_to([0])


def test_increase_is_capped_at_one_hundred(key: Harness) -> None:
    key.deck_levels[DEVICE] = 95

    assert_that(_run(key, mode="increase", value=10)).contains_entry({"value": 100})
    assert_that(_sets(key)).is_equal_to([100])


def test_set_sends_the_value_without_asking_for_the_level(key: Harness) -> None:
    result = _run(key, mode="set", value=75)

    assert_that(result).contains_entry({"value": 75})
    assert_that(_sets(key)).is_equal_to([75])
    assert_that(key.deck_gets).is_empty()


def test_defaults_are_increase_by_ten(key: Harness) -> None:
    assert_that(_run(key)).contains_entry({"value": 80})


def test_a_card_call_uses_the_cards_device(key: Harness) -> None:
    key.appear({})

    result = _run(key, with_card=True, mode="set", value=40)

    assert_that(result).contains_entry({"ok": True})
    assert_that(key.deck_sets).is_equal_to([{"device": DEVICE, "percent": 40}])


def test_no_device_is_an_error_and_nothing_is_sent(key: Harness) -> None:
    for args in ({"mode": "increase", "value": 10}, {"mode": "set", "value": 50}):
        result = _run(key, device="", **args)

        assert_that(result).contains_entry({"ok": False}, {"error": "no deck for this call"})
    assert_that(key.deck_sets).is_empty()
    assert_that(key.deck_gets).is_empty()
    assert_that([m["event"] for m in key.sent]).does_not_contain("set_deck_brightness", "get_deck_brightness")


def test_a_failing_level_lookup_is_an_error_and_nothing_is_set(key: Harness) -> None:
    result = _run(key, device="ghost", mode="increase", value=10)

    assert_that(result).contains_entry({"ok": False})
    assert_that(key.deck_sets).is_empty()


@pytest.mark.parametrize(
    "args", [{"mode": "toggle"}, {"mode": "set", "value": "x"}, {"mode": "set", "value": True}, {"value": 1.5}]
)
def test_bad_arguments_are_errors_and_nothing_is_sent(key: Harness, args: dict) -> None:
    assert_that(_run(key, **args)).contains_entry({"ok": False})
    assert_that(key.deck_sets).is_empty()


def test_a_value_is_clamped_to_zero_to_one_hundred(key: Harness) -> None:
    assert_that(_run(key, mode="set", value=500)).contains_entry({"value": 100})
    assert_that(_run(key, mode="set", value=-3)).contains_entry({"value": 0})


# --- the Level card ---


def _face(key: Harness) -> tuple[dict, str]:
    icon = key.recv_until("set_image")["payload"]
    title = key.recv_until("set_title")["payload"]["title"]
    return icon, title


def _appear(key: Harness) -> tuple[dict, str]:
    key.appear({})
    return _face(key)


def test_the_card_shows_the_logo_tinted_by_the_decks_level(key: Harness) -> None:
    icon, title = _appear(key)

    assert_that(icon).is_equal_to({"icon": "decker:logo", "color": "#b2b2b2"})
    assert_that(title).is_equal_to("70%")


def test_the_card_shows_a_dash_when_the_level_is_unavailable(key: Harness) -> None:
    del key.deck_levels[DEVICE]

    icon, title = _appear(key)

    assert_that(icon["color"]).is_equal_to("#808080")
    assert_that(title).is_equal_to("—")


def test_a_brightness_change_of_the_cards_deck_repaints_it(key: Harness) -> None:
    _appear(key)

    key.send_event("deck_brightness_changed", {"device": DEVICE, "percent": 100})

    icon, title = _face(key)
    assert_that(title).is_equal_to("100%")
    assert_that(icon["color"]).is_equal_to("#ffffff")


def test_a_change_of_another_deck_does_not_repaint_the_card(key: Harness) -> None:
    _appear(key)

    key.send_event("deck_brightness_changed", {"device": "other", "percent": 10})
    key.send_event("deck_brightness_changed", {"device": DEVICE, "percent": 20})

    assert_that(_face(key)[1]).is_equal_to("20%")


def test_a_card_that_disappeared_is_not_repainted(key: Harness) -> None:
    _appear(key)
    key.send_event("will_disappear", {}, "c1")
    _wait_until(lambda: not _decks.faces_on(DEVICE))

    key.send_event("deck_brightness_changed", {"device": DEVICE, "percent": 20})
    key.send_event("ping")

    key.recv_until("pong")
    assert_that([e for e in key.seen if e == "set_title"]).is_length(1)


# --- variables ---


def _variable(key: Harness, name: str) -> dict:
    key.send_event("get_variable", {"request": f"v-{name}", "name": name})
    return key.recv_until("variable_value")["payload"]


def _barrier(key: Harness) -> None:
    key.send_event("ping")
    key.recv_until("pong")


def test_a_connected_deck_registers_its_variable(key: Harness) -> None:
    key.connect(DEVICE)

    assert_that(key.recv_until("register_variable")["payload"]["name"]).is_equal_to(f"deck_brightness_level_{DEVICE}")


def test_the_first_variable_is_the_first_connected_decks_level(key: Harness) -> None:
    key.deck_levels["dev0"] = 12
    key.connect(DEVICE)
    key.connect("dev0")
    _barrier(key)

    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"ok": True}, {"value": "12"})
    assert_that(_variable(key, f"deck_brightness_level_{DEVICE}")).contains_entry({"value": "70"})


def test_a_deck_that_is_not_connected_has_no_value(key: Harness) -> None:
    _barrier(key)

    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"ok": True}, {"value": ""})
    assert_that(_variable(key, "deck_brightness_level_nope")).contains_entry({"ok": True}, {"value": None})


def test_a_deck_whose_level_cannot_be_read_gives_an_empty_value(key: Harness) -> None:
    del key.deck_levels[DEVICE]
    key.connect(DEVICE)
    _barrier(key)

    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"ok": True}, {"value": ""})


def test_a_brightness_change_updates_both_variables(key: Harness) -> None:
    key.connect(DEVICE)
    _barrier(key)

    key.send_event("deck_brightness_changed", {"device": DEVICE, "percent": 33})

    signalled = set()
    while not {"deck_brightness_level", f"deck_brightness_level_{DEVICE}"} <= signalled:
        signalled.add(key.recv_until("variable_updated")["payload"]["name"])
    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"value": "33"})
    assert_that(_variable(key, f"deck_brightness_level_{DEVICE}")).contains_entry({"value": "33"})


def test_a_disconnect_unregisters_the_variable_and_moves_first(key: Harness) -> None:
    key.deck_levels["dev2"] = 20
    key.connect(DEVICE)
    key.connect("dev2")
    _barrier(key)
    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"value": "70"})

    key.disconnect(DEVICE)

    assert_that(key.recv_until("unregister_variable")["payload"]["name"]).is_equal_to(f"deck_brightness_level_{DEVICE}")
    assert_that(key.recv_until("variable_updated")["payload"]["name"]).is_equal_to("deck_brightness_level")
    assert_that(_variable(key, "deck_brightness_level")).contains_entry({"value": "20"})
    assert_that(_variable(key, f"deck_brightness_level_{DEVICE}")).contains_entry({"value": None})


# --- the manifest ---


def _card(card_id: str) -> Any:
    return next(c for c in _MANIFEST.cards if c.id == card_id)


def _bindings(card_id: str) -> dict[str, tuple[str, dict]]:
    return {g: (b.action, dict(b.args)) for g, b in _card(card_id).bindings.items()}


def _args(mode: str, value: int) -> tuple[str, dict]:
    return (_ACTION, {"mode": mode, "value": value})


def test_manifest_level_card_bindings_and_a_resolvable_catalogue_icon() -> None:
    assert_that(_card(_LEVEL).icon).is_equal_to("icons/utilities")
    assert_that(_bindings(_LEVEL)).is_equal_to(
        {"press": _args("increase", 10), "double_press": _args("decrease", 10), "long_press": _args("set", 75)}
    )


@pytest.mark.parametrize(
    ("mode", "value", "expected"),
    [
        ("increase", 5, 75),
        ("decrease", 5, 65),
        ("increase", 10, 80),
        ("decrease", 10, 60),
        ("set", 75, 75),
        ("set", 25, 25),
    ],
)
def test_the_former_up_and_down_presets_move_the_deck(key: Harness, mode: str, value: int, expected: int) -> None:
    result = _run(key, mode=mode, value=value)

    assert_that(result).contains_entry({"ok": True}, {"value": expected})
    assert_that(key.deck_sets).is_equal_to([{"device": DEVICE, "percent": expected}])


def test_manifest_action_is_global_with_mode_and_value() -> None:
    action = next(a for a in _MANIFEST.actions if a.id == _ACTION)
    fields = {e.key: e for e in action.settings if hasattr(e, "key")}

    assert_that(action.scope).is_equal_to("global")
    assert_that(set(fields)).is_equal_to({"mode", "value"})
    assert_that([o["value"] for o in fields["mode"].extra["options"]]).is_equal_to(["increase", "decrease", "set"])
    assert_that(fields["value"].default).is_equal_to(10)


def test_manifest_declares_the_deck_variable_and_the_pattern() -> None:
    declared = [(v.name, v.pattern) for v in _MANIFEST.variables]

    assert_that(declared).contains(("deck_brightness_level", None), (None, "deck_brightness_level_{device}"))
