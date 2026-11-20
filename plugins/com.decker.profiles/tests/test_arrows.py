"""Next and Previous profile keys: the recoloured caret and the switch_profile request."""

import base64
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent))
from _profiles_harness import Harness, load_plugin  # noqa: E402


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="next_key")
def next_fixture(plugin: ModuleType):
    harness = Harness(plugin, "com.decker.profiles.next", "NextCard")
    yield harness
    harness.close()


@pytest.fixture(name="previous_key")
def previous_fixture(plugin: ModuleType):
    harness = Harness(plugin, "com.decker.profiles.previous", "PreviousCard")
    yield harness
    harness.close()


def test_next_press_requests_the_next_profile(next_key: Harness) -> None:
    next_key.appear({"wrap": False, "color": "#ffffff"})
    next_key.press()

    assert_that(next_key.recv_until("switch_profile")["payload"]).is_equal_to({"to": "next", "wrap": False})


def test_previous_press_requests_the_previous_profile_with_wrap(previous_key: Harness) -> None:
    previous_key.appear({"wrap": True})
    previous_key.press()

    assert_that(previous_key.recv_until("switch_profile")["payload"]).is_equal_to({"to": "previous", "wrap": True})


@pytest.mark.parametrize("wrap", ["yes", 1, None])
def test_only_true_counts_as_wrap(next_key: Harness, wrap) -> None:
    next_key.appear({"wrap": wrap})
    next_key.press()

    assert_that(next_key.recv_until("switch_profile")["payload"]["wrap"]).is_false()


def test_draws_a_svg_caret_in_the_chosen_colour(next_key: Harness) -> None:
    next_key.appear({"color": "#ff0000"})

    payload = next_key.recv_until("set_image")["payload"]

    assert_that(payload["format"]).is_equal_to("svg")
    svg = base64.b64decode(payload["image"]).decode()
    assert_that(svg).contains("#ff0000").does_not_contain("currentColor")


def test_a_bad_colour_falls_back_to_white(next_key: Harness) -> None:
    next_key.appear({"color": "red"})

    svg = base64.b64decode(next_key.recv_until("set_image")["payload"]["image"]).decode()

    assert_that(svg).contains("#ffffff")


def test_settings_change_redraws(next_key: Harness) -> None:
    next_key.appear({"color": "#ff0000"})
    next_key.recv_until("set_image")

    next_key.change({"color": "#00ff00"})

    svg = base64.b64decode(next_key.recv_until("set_image")["payload"]["image"]).decode()
    assert_that(svg).contains("#00ff00")
