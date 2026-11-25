"""Go to profile action: the press goes to the chosen profile."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _profiles_harness import Harness, load_plugin  # noqa: E402

_ACTION = "com.decker.profiles.goto"
_PROFILE = {"profile_id": 2, "name": "Work", "index": 2, "icon": "pack:a/b.svg"}
_NONE = {"profile_id": -1, "name": "", "index": 0, "icon": ""}


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _ACTION)
    yield harness
    harness.close()


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
