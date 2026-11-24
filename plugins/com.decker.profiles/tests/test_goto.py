"""Go to profile key: icon and name from the press binding's profile, the action goes there."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _profiles_harness import Harness, goto_bindings, load_plugin  # noqa: E402

_ACTION = "com.decker.profiles.goto"
_PROFILE = {"profile_id": 2, "name": "Work", "index": 2, "icon": "pack:a/b.svg"}
_NONE = {"profile_id": -1, "name": "", "index": 0, "icon": ""}


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _ACTION, "GotoCard")
    yield harness
    harness.close()


def _of(messages: list[dict], event: str) -> list[dict]:
    return [m["payload"] for m in messages if m["event"] == event]


def _appear(key: Harness, profile: Any) -> None:
    key.appear({}, goto_bindings(profile))


def test_goto_action_goes_to_the_profile(key: Harness) -> None:
    result = key.run_action(_ACTION, {"profile": _PROFILE})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_profile")).is_equal_to([{"profile_id": 2, "request": key.request}])


def test_profile_zero_is_a_real_profile(key: Harness) -> None:
    key.run_action(_ACTION, {"profile": {**_PROFILE, "profile_id": 0}})

    assert_that(key.sent_payloads("switch_profile")).is_equal_to([{"profile_id": 0, "request": key.request}])


@pytest.mark.parametrize("profile", [_NONE, None, "2", 5, {"profile_id": "2"}, {"profile_id": True}, []])
def test_goto_action_without_a_profile_does_nothing(key: Harness, profile: Any) -> None:
    result = key.run_action(_ACTION, {"profile": profile})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_profile")).is_empty()


def test_goto_action_without_a_card_fails(key: Harness) -> None:
    result = key.run_action(_ACTION, {"profile": _PROFILE}, with_card=False)

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("needs a card")


def test_action_run_by_an_appeared_card_uses_its_own_key(key: Harness) -> None:
    _appear(key, _PROFILE)
    key.recv_until("set_title")

    result = key.run_action(_ACTION, {"profile": _PROFILE})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_profile")).is_equal_to([{"profile_id": 2}])


def test_goto_card_shows_press_binding_profile_icon_and_name(key: Harness) -> None:
    _appear(key, _PROFILE)

    assert_that(key.recv_until("set_image")["payload"]).is_equal_to({"icon": "pack:a/b.svg"})
    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Work"})


def test_the_decker_icon_ref_is_shown_too(key: Harness) -> None:
    _appear(key, {**_PROFILE, "profile_id": 0, "name": "Default", "icon": "decker:logo"})

    assert_that(key.recv_until("set_image")["payload"]["icon"]).is_equal_to("decker:logo")


def test_goto_card_follows_a_changed_binding(key: Harness) -> None:
    _appear(key, _PROFILE)
    key.recv_until("set_title")

    key.change({}, goto_bindings({**_PROFILE, "name": "Renamed"}))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Renamed"})


def _cleared(messages: list[dict]) -> None:
    assert_that(_of(messages, "set_image")[0]).is_equal_to({"image": None})
    assert_that(_of(messages, "set_title")).is_equal_to([{"title": ""}])


def test_goto_card_clears_when_press_rebound(key: Harness) -> None:
    key.appear({}, goto_bindings(_PROFILE, action="com.decker.profiles.next"))

    _cleared(key.collect_settled())


def test_goto_card_clears_when_rebound_after_showing_a_profile(key: Harness) -> None:
    _appear(key, _PROFILE)
    key.recv_until("set_title")

    key.change({}, goto_bindings(_PROFILE, action="com.decker.core.nothing"))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


@pytest.mark.parametrize("bindings", [{}, {"press": {"action": "com.decker.core.nothing"}}, {"press": "x"}])
def test_goto_card_clears_without_a_goto_press_binding(key: Harness, bindings: Any) -> None:
    key.appear({}, bindings)

    _cleared(key.collect_settled())


@pytest.mark.parametrize("garbage", [_NONE, None, "2", 5, {"profile_id": "2"}, {"profile_id": True}, []])
def test_goto_card_clears_for_garbage_profile(key: Harness, garbage: Any) -> None:
    _appear(key, garbage)

    _cleared(key.collect_settled())


def test_names_with_braces_or_newlines_are_passed_through_as_text(key: Harness) -> None:
    _appear(key, {**_PROFILE, "name": "A {b}\nC"})

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "A {b}\nC"})
