"""Go to profile key: icon and title from the chosen profile, press goes there."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _profiles_harness import Harness, load_plugin  # noqa: E402

_ACTION = "com.decker.profiles.goto"
_EMPTY = {"profile_id": -1, "name": "", "index": 0, "icon": ""}


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _ACTION, "GotoCard")
    yield harness
    harness.close()


def _profile(profile_id: int = 2, name: str = "Work", icon: str = "pack:a/b.svg") -> dict[str, Any]:
    return {"profile": {"profile_id": profile_id, "name": name, "index": 2, "icon": icon}}


def _of(messages: list[dict], event: str) -> list[dict]:
    return [m["payload"] for m in messages if m["event"] == event]


def test_shows_the_profiles_icon_and_name(key: Harness) -> None:
    key.appear(_profile())

    assert_that(key.recv_until("set_image")["payload"]).is_equal_to({"icon": "pack:a/b.svg"})
    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Work"})


def test_the_decker_icon_ref_is_shown_too(key: Harness) -> None:
    key.appear(_profile(0, "Default", "decker:logo"))

    assert_that(key.recv_until("set_image")["payload"]["icon"]).is_equal_to("decker:logo")


def test_press_goes_to_the_chosen_profile(key: Harness) -> None:
    key.appear(_profile())
    key.recv_until("set_title")

    key.press()

    assert_that(key.recv_until("switch_profile")["payload"]).is_equal_to({"profile_id": 2})


def test_profile_zero_is_a_real_profile(key: Harness) -> None:
    key.appear(_profile(0, "Default", "decker:logo"))
    key.recv_until("set_title")

    key.press()

    assert_that(key.recv_until("switch_profile")["payload"]).is_equal_to({"profile_id": 0})


def test_no_profile_clears_the_key_and_press_does_nothing(key: Harness) -> None:
    key.appear({"profile": _EMPTY})
    key.press()

    messages = key.collect_settled()
    assert_that(_of(messages, "switch_profile")).is_empty()
    assert_that(_of(messages, "set_image")[0]).is_equal_to({"image": None})
    assert_that(_of(messages, "set_title")).is_equal_to([{"title": ""}])


@pytest.mark.parametrize("garbage", [None, "2", 5, {"profile_id": "2"}, {"profile_id": True}, []])
def test_garbage_profile_value_does_not_crash(key: Harness, garbage: Any) -> None:
    key.appear({"profile": garbage})
    key.press()

    assert_that(_of(key.collect_settled(), "switch_profile")).is_empty()


def test_missing_profile_key_does_not_crash(key: Harness) -> None:
    key.appear({})
    key.press()

    assert_that(_of(key.collect_settled(), "switch_profile")).is_empty()


def test_rename_updates_the_title_and_press_keeps_the_id(key: Harness) -> None:
    key.appear(_profile())
    key.recv_until("set_title")

    key.change(_profile(name="Renamed"))
    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Renamed"})
    key.press()

    assert_that(key.recv_until("switch_profile")["payload"]).is_equal_to({"profile_id": 2})


def test_names_with_braces_or_newlines_are_passed_through_as_text(key: Harness) -> None:
    key.appear(_profile(name="A {b}\nC"))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "A {b}\nC"})
