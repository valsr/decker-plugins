"""Go to page key: title from the chosen page, press goes there."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _pages_harness import Harness, goto_bindings, load_plugin  # noqa: E402

_ACTION = "com.decker.pages.goto"


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _ACTION, "GotoCard")
    yield harness
    harness.close()


_PAGE = {"page_id": "p2", "name": "Settings", "index": 2}
_NONE = {"page_id": "", "name": "", "index": 0}


def _titles(messages: list[dict]) -> list[str]:
    return [m["payload"]["title"] for m in messages if m["event"] == "set_title"]


def _switches(messages: list[dict]) -> list[dict]:
    return [m["payload"] for m in messages if m["event"] == "switch_page"]


def _appear(key: Harness, page: Any) -> None:
    key.appear({}, goto_bindings(page))


def test_goto_action_goes_to_the_page(key: Harness) -> None:
    result = key.run_action(_ACTION, {"profile": "", "page": _PAGE})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_page")).is_equal_to([{"page_id": "p2"}])


@pytest.mark.parametrize("page", [_NONE, None, "p2", 5, {"page_id": 5}, []])
def test_goto_action_without_a_page_does_nothing(key: Harness, page: Any) -> None:
    result = key.run_action(_ACTION, {"profile": "", "page": page})

    assert_that(result["ok"]).is_true()
    assert_that(_switches(key.sent)).is_empty()


def test_goto_action_without_a_card_fails(key: Harness) -> None:
    result = key.run_action(_ACTION, {"profile": "", "page": _PAGE}, with_card=False)

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("needs a card")


def test_goto_card_title_follows_press_binding_page(key: Harness) -> None:
    _appear(key, _PAGE)

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To Settings"})


def test_goto_card_title_updates_when_the_binding_changes(key: Harness) -> None:
    _appear(key, _PAGE)
    key.recv_until("set_title")

    key.change({}, goto_bindings({**_PAGE, "name": "Renamed"}))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To Renamed"})


def test_goto_card_title_empty_when_press_rebound(key: Harness) -> None:
    key.appear({}, goto_bindings(_PAGE, action="com.decker.pages.next"))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


@pytest.mark.parametrize("bindings", [{}, {"press": {"action": "com.decker.core.nothing"}}, {"press": "x"}])
def test_goto_card_title_empty_without_a_goto_press_binding(key: Harness, bindings: Any) -> None:
    key.appear({}, bindings)

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


@pytest.mark.parametrize("garbage", [_NONE, None, "p2", 5, {"page_id": 5}, []])
def test_goto_card_title_empty_for_garbage_page(key: Harness, garbage: Any) -> None:
    _appear(key, garbage)

    assert_that(_titles(key.collect_settled())).is_equal_to([""])


def test_names_with_braces_or_newlines_are_passed_through_as_text(key: Harness) -> None:
    _appear(key, {**_PAGE, "name": "A {b}\nC"})

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To A {b}\nC"})
