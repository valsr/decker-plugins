"""Go to page action: the press goes to the chosen page."""

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
    harness = Harness(plugin, _ACTION)
    yield harness
    harness.close()


_PAGE = {"page_id": "p2", "name": "Settings", "index": 2}
_NONE = {"page_id": "", "name": "", "index": 0}


def _switches(messages: list[dict]) -> list[dict]:
    return [m["payload"] for m in messages if m["event"] == "switch_page"]


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
