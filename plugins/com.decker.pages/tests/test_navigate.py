"""Next and previous page actions: they switch the calling card's device, wrapping only on ``wrap: true``."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _pages_harness import Harness, load_plugin  # noqa: E402

_NEXT = "com.decker.pages.next"
_PREVIOUS = "com.decker.pages.previous"
_EVENT = "switch_page"


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _NEXT)
    yield harness
    harness.close()


def test_next_action_switches_the_card_device_page_with_wrap(key: Harness) -> None:
    result = key.run_action(_NEXT, {"wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads(_EVENT)).is_equal_to([{"to": "next", "wrap": True}])


def test_next_action_does_not_wrap_by_default(key: Harness) -> None:
    key.run_action(_NEXT, {"wrap": False})

    assert_that(key.sent_payloads(_EVENT)).is_equal_to([{"to": "next", "wrap": False}])


@pytest.mark.parametrize("wrap", ["yes", 1, None])
def test_only_true_counts_as_wrap(key: Harness, wrap: Any) -> None:
    key.run_action(_NEXT, {"wrap": wrap})

    assert_that(key.sent_payloads(_EVENT)[0]["wrap"]).is_false()


def test_previous_action(key: Harness) -> None:
    result = key.run_action(_PREVIOUS, {"wrap": False})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads(_EVENT)).is_equal_to([{"to": "previous", "wrap": False}])


@pytest.mark.parametrize("action_id", [_NEXT, _PREVIOUS])
def test_actions_without_a_card_fail(key: Harness, action_id: str) -> None:
    result = key.run_action(action_id, {"wrap": False}, with_card=False)

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("needs a card")
    assert_that(key.sent_payloads(_EVENT)).is_empty()
