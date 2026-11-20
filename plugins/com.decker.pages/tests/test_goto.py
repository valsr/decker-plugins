"""Go to page key: title from the chosen page, press goes there."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _pages_harness import Harness, load_plugin  # noqa: E402

_ACTION = "com.decker.pages.goto"


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _ACTION, "GotoCard")
    yield harness
    harness.close()


def _page(page_id: str = "p2", name: str = "Settings", index: int = 2) -> dict[str, Any]:
    return {"page": {"page_id": page_id, "name": name, "index": index}}


def _titles(messages: list[dict]) -> list[str]:
    return [m["payload"]["title"] for m in messages if m["event"] == "set_title"]


def _switches(messages: list[dict]) -> list[dict]:
    return [m["payload"] for m in messages if m["event"] == "switch_page"]


def test_title_is_go_to_the_page_name(key: Harness) -> None:
    key.appear(_page())

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To Settings"})


def test_press_goes_to_the_chosen_page(key: Harness) -> None:
    key.appear(_page())
    key.recv_until("set_title")

    key.press()

    assert_that(key.recv_until("switch_page")["payload"]).is_equal_to({"page_id": "p2"})


def test_no_page_chosen_has_an_empty_title_and_press_does_nothing(key: Harness) -> None:
    key.appear({"page": {"page_id": "", "name": "", "index": 0}})
    key.press()

    messages = key.collect_settled()
    assert_that(_titles(messages)).is_equal_to([""])
    assert_that(_switches(messages)).is_empty()


def test_deleted_page_resolves_empty_so_nothing_happens(key: Harness) -> None:
    key.appear(_page())
    key.recv_until("set_title")

    key.change({"page": {"page_id": "", "name": "", "index": 0}})
    key.press()

    messages = key.collect_settled()
    assert_that(_titles(messages)).is_equal_to([""])
    assert_that(_switches(messages)).is_empty()


@pytest.mark.parametrize("garbage", [None, "p2", 5, {"page_id": 5}, []])
def test_garbage_page_value_does_not_crash(key: Harness, garbage: Any) -> None:
    key.appear({"page": garbage})
    key.press()

    messages = key.collect_settled()
    assert_that(_titles(messages)).is_equal_to([""])
    assert_that(_switches(messages)).is_empty()


def test_missing_page_key_does_not_crash(key: Harness) -> None:
    key.appear({})
    key.press()

    assert_that(_switches(key.collect_settled())).is_empty()


def test_rename_updates_the_title(key: Harness) -> None:
    key.appear(_page())
    key.recv_until("set_title")

    key.change(_page(name="Renamed"))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To Renamed"})


def test_names_with_braces_or_newlines_are_passed_through_as_text(key: Harness) -> None:
    key.appear(_page(name="A {b}\nC"))

    assert_that(key.recv_until("set_title")["payload"]).is_equal_to({"title": "Go To A {b}\nC"})


def test_press_after_rename_still_uses_the_page_id(key: Harness) -> None:
    key.appear(_page())
    key.recv_until("set_title")
    key.change(_page(name="Renamed"))
    key.recv_until("set_title")

    key.press()

    assert_that(key.recv_until("switch_page")["payload"]).is_equal_to({"page_id": "p2"})
