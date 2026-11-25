"""Brightness action, cards and variables, through the SDK loop with a fake backend."""

import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

sys.path.insert(0, str(Path(__file__).parent))
from _harness import PLUGIN_DIR, Harness, load_plugin  # noqa: E402
from brightness import BrightnessError, Monitor  # noqa: E402
from display_brightness import cache, set_backend_for_tests  # noqa: E402

_ACTION = "com.decker.utilities.brightness"
_LEVEL = "com.decker.utilities.brightness-level"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")


class FakeBackend:
    def __init__(self, levels: dict[str, int]) -> None:
        self.levels = dict(levels)
        self.vanished: set[str] = set()
        self.failing: set[str] = set()

    def list_monitors(self) -> list[Monitor]:
        return [Monitor(i, i.upper()) for i in self.levels if i not in self.vanished]

    def get(self, monitor_id: str) -> int:
        if monitor_id in self.vanished:
            raise BrightnessError(f"monitor {monitor_id} not found")
        return self.levels[monitor_id]

    def set(self, monitor_id: str, percent: int) -> None:
        if monitor_id in self.vanished or monitor_id in self.failing:
            raise BrightnessError(f"monitor {monitor_id} not found")
        self.levels[monitor_id] = percent


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="backend")
def backend_fixture() -> FakeBackend:
    backend = FakeBackend({"a": 50, "b": 70})
    set_backend_for_tests(backend)
    return backend


def _open(plugin: ModuleType) -> Harness:
    return Harness(plugin, _LEVEL, "BrightnessLevelCard")


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType, backend: FakeBackend):
    harness = _open(plugin)
    yield harness
    harness.close()


def _wait_monitors(count: int) -> None:
    deadline = time.monotonic() + 5
    while len(cache().monitors()) != count:
        assert time.monotonic() < deadline, "monitor list did not settle"
        time.sleep(0.01)


def _run(key: Harness, **args: Any) -> dict:
    return key.run_action(_ACTION, args, with_card=False)


# --- the action ---


def test_increase_adds_the_value_and_returns_the_new_level(key: Harness, backend: FakeBackend) -> None:
    result = _run(key, mode="increase", value=10, monitor="a")

    assert_that(result).contains_entry({"ok": True}, {"value": 60})
    assert_that(backend.levels["a"]).is_equal_to(60)


def test_decrease_subtracts_and_clamps_at_zero(key: Harness, backend: FakeBackend) -> None:
    result = _run(key, mode="decrease", value=80, monitor="a")

    assert_that(result).contains_entry({"value": 0})
    assert_that(backend.levels["a"]).is_equal_to(0)


def test_increase_clamps_at_one_hundred(key: Harness, backend: FakeBackend) -> None:
    assert_that(_run(key, mode="increase", value=90, monitor="b")).contains_entry({"value": 100})


def test_set_writes_the_value(key: Harness, backend: FakeBackend) -> None:
    assert_that(_run(key, mode="set", value=75, monitor="a")).contains_entry({"value": 75})
    assert_that(backend.levels["a"]).is_equal_to(75)


def test_defaults_are_increase_by_ten_on_all_monitors(key: Harness, backend: FakeBackend) -> None:
    result = _run(key)

    assert_that(result).contains_entry({"value": 60})
    assert_that(backend.levels).is_equal_to({"a": 60, "b": 80})


def test_all_applies_to_every_monitor_and_returns_the_first_ones_level(key: Harness, backend: FakeBackend) -> None:
    result = _run(key, mode="decrease", value=20, monitor="all")

    assert_that(result).contains_entry({"value": 30})
    assert_that(backend.levels).is_equal_to({"a": 30, "b": 50})


def test_unknown_monitor_is_not_available(key: Harness, backend: FakeBackend) -> None:
    result = _run(key, mode="set", value=10, monitor="zzz")

    assert_that(result).contains_entry({"ok": False}, {"error": "monitor not available"})
    assert_that(backend.levels).is_equal_to({"a": 50, "b": 70})


def test_no_monitors_is_a_clear_error(plugin: ModuleType) -> None:
    set_backend_for_tests(FakeBackend({}))
    key = _open(plugin)
    try:
        for monitor in ("all", "a"):
            result = _run(key, mode="increase", value=10, monitor=monitor)

            assert_that(result).contains_entry({"ok": False}, {"error": "no monitor found"})
    finally:
        key.close()


def test_a_monitor_vanishing_after_listing_is_a_clear_error(key: Harness, backend: FakeBackend) -> None:
    _wait_monitors(2)
    backend.vanished.add("a")

    result = _run(key, mode="set", value=10, monitor="a")

    assert_that(result).contains_entry({"ok": False})
    assert_that(result["error"]).contains("a").contains("not found")


def test_all_sets_the_rest_when_one_monitor_fails_and_reports_it(key: Harness, backend: FakeBackend) -> None:
    _wait_monitors(2)
    backend.failing.add("a")

    result = _run(key, mode="set", value=10, monitor="all")

    assert_that(result).contains_entry({"ok": False})
    assert_that(result["error"]).contains("monitor a not found")
    assert_that(backend.levels).is_equal_to({"a": 50, "b": 10})


@pytest.mark.parametrize("args", [{"mode": "sideways"}, {"value": "ten"}, {"value": True}, {"monitor": 3}])
def test_bad_arguments_are_errors_that_change_nothing(key: Harness, backend: FakeBackend, args: dict) -> None:
    result = _run(key, **args)

    assert_that(result).contains_entry({"ok": False})
    assert_that(backend.levels).is_equal_to({"a": 50, "b": 70})


def test_a_level_card_call_uses_the_cards_monitor_when_the_binding_says_all(key: Harness, backend: FakeBackend) -> None:
    key.appear({"monitor": "b"})

    result = key.run_action(_ACTION, {"mode": "set", "value": 5, "monitor": "all"})

    assert_that(result).contains_entry({"ok": True})
    assert_that(backend.levels).is_equal_to({"a": 50, "b": 5})


def test_a_level_card_binding_naming_a_monitor_wins_over_the_card_setting(key: Harness, backend: FakeBackend) -> None:
    key.appear({"monitor": "b"})

    key.run_action(_ACTION, {"mode": "set", "value": 5, "monitor": "a"})

    assert_that(backend.levels).is_equal_to({"a": 5, "b": 70})


# --- options ---


def test_monitor_options_list_all_then_the_labelled_monitors(plugin: ModuleType) -> None:
    set_backend_for_tests(FakeBackend({"a": 1, "b": 2}))
    cache().poll_once()

    assert_that(plugin.monitor_options()).is_equal_to(
        [
            {"label": "All monitors", "value": "all"},
            {"label": "A", "value": "a"},
            {"label": "B", "value": "b"},
        ]
    )


def test_monitor_options_with_no_monitors_still_offer_all(plugin: ModuleType) -> None:
    assert_that(plugin.monitor_options()).is_equal_to([{"label": "All monitors", "value": "all"}])


# --- the Level card ---


def _face(key: Harness) -> tuple[dict, str]:
    icon = key.recv_until("set_image")["payload"]
    title = key.recv_until("set_title")["payload"]["title"]
    return icon, title


def _latest_title(key: Harness, wanted: str) -> None:
    while key.recv_until("set_title")["payload"]["title"] != wanted:
        pass


def test_level_card_shows_the_average_for_all_with_a_grey_tinted_sun(key: Harness) -> None:
    key.appear({"monitor": "all"})

    _latest_title(key, "60%")

    assert_that(key.seen).contains("set_image")


def test_level_card_icon_is_the_bundled_sun_tinted_by_the_level(key: Harness) -> None:
    _wait_monitors(2)
    key.appear({"monitor": "a"})

    icon, title = _face(key)

    assert_that(icon).is_equal_to({"icon": "fas:sun", "color": "#808080"})
    assert_that(title).is_equal_to("50%")


def test_level_card_for_one_monitor_shows_that_monitors_level(key: Harness) -> None:
    _wait_monitors(2)
    key.appear({"monitor": "b"})

    assert_that(_face(key)[1]).is_equal_to("70%")


def test_level_card_repaints_when_the_cache_changes(key: Harness, backend: FakeBackend) -> None:
    _wait_monitors(2)
    key.appear({"monitor": "a"})
    _face(key)

    backend.levels["a"] = 100
    cache().poll_once()

    icon, title = _face(key)
    assert_that(title).is_equal_to("100%")
    assert_that(icon["color"]).is_equal_to("#ffffff")


def test_level_card_repaints_after_a_settings_change(key: Harness) -> None:
    _wait_monitors(2)
    key.appear({"monitor": "a"})
    _face(key)

    key.change({"monitor": "b"})

    assert_that(_face(key)[1]).is_equal_to("70%")


def test_level_card_shows_a_dash_when_there_is_no_monitor(plugin: ModuleType) -> None:
    set_backend_for_tests(FakeBackend({}))
    key = _open(plugin)
    try:
        key.appear({"monitor": "all"})

        icon, title = _face(key)

        assert_that(title).is_equal_to("—")
        assert_that(icon["icon"]).is_equal_to("fas:sun")
    finally:
        key.close()


def test_level_card_shows_a_dash_for_a_monitor_that_is_gone(key: Harness) -> None:
    _wait_monitors(2)
    key.appear({"monitor": "gone"})

    assert_that(_face(key)[1]).is_equal_to("—")


# --- variables ---


def _variable(key: Harness, name: str) -> dict:
    key.send_event("get_variable", {"request": f"v-{name}", "name": name})
    return key.recv_until("variable_value")["payload"]


def test_brightness_level_is_the_first_monitors_level(key: Harness) -> None:
    _wait_monitors(2)

    assert_that(_variable(key, "brightness_level")).contains_entry({"ok": True}, {"value": "50"})


def test_per_monitor_variables_use_a_one_based_index(key: Harness) -> None:
    _wait_monitors(2)

    assert_that(_variable(key, "brightness_level_1")).contains_entry({"value": "50"})
    assert_that(_variable(key, "brightness_level_2")).contains_entry({"value": "70"})


def test_a_per_monitor_variable_beyond_the_monitors_has_no_value(key: Harness) -> None:
    _wait_monitors(2)

    result = _variable(key, "brightness_level_3")

    assert_that(result).contains_entry({"ok": True}, {"value": None})


def test_variables_are_empty_when_there_is_no_monitor(plugin: ModuleType) -> None:
    set_backend_for_tests(FakeBackend({}))
    key = _open(plugin)
    try:
        assert_that(_variable(key, "brightness_level")).contains_entry({"ok": True}, {"value": ""})
    finally:
        key.close()


def test_monitors_are_registered_as_pattern_variables(key: Harness) -> None:
    names = set()
    while names != {"brightness_level_1", "brightness_level_2"}:
        names.add(key.recv_until("register_variable")["payload"]["name"])


def test_a_vanished_monitor_is_unregistered_and_the_rest_signalled(key: Harness, backend: FakeBackend) -> None:
    _wait_monitors(2)
    backend.vanished.add("b")
    cache().poll_once()

    gone = key.recv_until("unregister_variable")["payload"]["name"]

    assert_that(gone).is_equal_to("brightness_level_2")
    assert_that(key.recv_until("variable_updated")["payload"]["name"]).starts_with("brightness_level")


def test_a_returning_monitor_is_registered_again(key: Harness, backend: FakeBackend) -> None:
    _wait_monitors(2)
    backend.vanished.add("b")
    cache().poll_once()
    key.recv_until("unregister_variable")

    backend.vanished.clear()
    cache().poll_once()

    assert_that(key.recv_until("register_variable")["payload"]["name"]).is_equal_to("brightness_level_2")


def test_a_change_signals_the_level_variables(key: Harness) -> None:
    _wait_monitors(2)

    _run(key, mode="set", value=33, monitor="a")

    signalled = set()
    while "brightness_level" not in signalled:
        signalled.add(key.recv_until("variable_updated")["payload"]["name"])


# --- the manifest ---


def _card(card_id: str) -> Any:
    return next(c for c in _MANIFEST.cards if c.id == card_id)


def _bindings(card_id: str) -> dict[str, tuple[str, dict]]:
    return {g: (b.action, dict(b.args)) for g, b in _card(card_id).bindings.items()}


def _args(mode: str, value: int, monitor: str | None = None) -> tuple[str, dict]:
    args: dict[str, Any] = {"mode": mode, "value": value}
    if monitor is not None:
        args["monitor"] = monitor
    return (_ACTION, args)


def test_manifest_level_card_bindings_and_icon() -> None:
    assert_that(_card(_LEVEL).icon).is_equal_to("fas:sun")
    assert_that(_bindings(_LEVEL)).is_equal_to(
        {
            "press": _args("increase", 10),
            "double_press": _args("decrease", 10),
            "long_press": _args("set", 75),
        }
    )


@pytest.mark.parametrize(
    ("mode", "value", "expected"),
    [
        ("increase", 10, (60, 80)),
        ("increase", 5, (55, 75)),
        ("decrease", 10, (40, 60)),
        ("decrease", 5, (45, 65)),
        ("set", 75, (75, 75)),
        ("set", 25, (25, 25)),
    ],
)
def test_the_former_up_and_down_presets_act_on_all_monitors(
    key: Harness, backend: FakeBackend, mode: str, value: int, expected: tuple[int, int]
) -> None:
    result = _run(key, mode=mode, value=value, monitor="all")

    assert_that(result).contains_entry({"ok": True})
    assert_that(backend.levels).is_equal_to({"a": expected[0], "b": expected[1]})


def test_manifest_level_card_monitor_setting_is_a_dynamic_choice_defaulting_to_all() -> None:
    field = next(e for e in _card(_LEVEL).settings if getattr(e, "key", "") == "monitor")

    assert_that(field.type).is_equal_to("choice")
    assert_that(field.default).is_equal_to("all")
    assert_that(field.extra["options_source"]).is_equal_to("monitors")


def test_manifest_action_settings() -> None:
    action = next(a for a in _MANIFEST.actions if a.id == _ACTION)
    fields = {e.key: e for e in action.settings if hasattr(e, "key")}

    assert_that(action.scope).is_equal_to("global")
    assert_that(fields["mode"].default).is_equal_to("increase")
    assert_that([o["value"] for o in fields["mode"].extra["options"]]).is_equal_to(["increase", "decrease", "set"])
    assert_that(fields["value"].default).is_equal_to(10)
    assert_that((fields["value"].extra["min"], fields["value"].extra["max"])).is_equal_to((0, 100))
    assert_that(fields["monitor"].default).is_equal_to("all")
    assert_that(fields["monitor"].extra["options_source"]).is_equal_to("monitors")


def test_manifest_declares_the_variable_and_the_pattern() -> None:
    declared = [(v.name, v.pattern) for v in _MANIFEST.variables]

    assert_that(declared).contains((("brightness_level", None)), (None, "brightness_level_{monitor}"))


# --- startup ordering ---


class _RecordingCard:
    context = "early"
    settings: dict = {"monitor": "a"}

    def __init__(self) -> None:
        self.titles: list[str] = []

    def set_icon(self, ref: str, color: str | None = None) -> None:
        pass

    def set_title(self, title: str) -> None:
        self.titles.append(title)


def test_a_card_tracked_before_the_poll_starts_still_repaints(backend: FakeBackend) -> None:
    from display_brightness import _service

    early = _RecordingCard()
    _service.track(early)  # type: ignore[arg-type]
    started = _service.begin_run()
    try:
        _wait_monitors(2)
        deadline = time.monotonic() + 5
        while not early.titles:  # the first poll's repaint must land before the level changes under it
            assert time.monotonic() < deadline, "the early card was never painted"
            time.sleep(0.01)
        backend.levels["a"] = 20
        cache().poll_once()

        assert_that(early.titles[-1]).is_equal_to("20%")
    finally:
        started.stop()


# --- teardown ---


def test_a_late_begin_run_after_teardown_does_not_touch_the_real_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import conftest
    import display_brightness

    asked: list[bool] = []
    monkeypatch.setattr(display_brightness, "default_backend", lambda: asked.append(True) or FakeBackend({}))
    session = conftest.hardware_free()
    next(session)
    list(session)  # teardown

    started = display_brightness._service.begin_run()
    started.stop()

    assert_that(asked).is_empty()
