"""Page and Profile: the global actions, run through a card in the call or through the call's device."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

sys.path.insert(0, str(Path(__file__).parent))
from _harness import PLUGIN_DIR, Harness, load_plugin  # noqa: E402

_PAGE = "com.decker.utilities.page"
_PROFILE = "com.decker.utilities.profile"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_DELETED_PAGE = {"page_id": "p9", "name": "", "index": 0, "profile_id": -1}
_DELETED_PROFILE = {"profile_id": -1, "name": "", "index": 0, "icon": ""}


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType):
    """Any card will do: the actions only need a key to run through (or none, with ``with_card=False``)."""
    harness = Harness(plugin, "com.decker.utilities.counter", "CounterCard")
    yield harness
    harness.close()


def _spec(action_id: str) -> Any:
    return next(a for a in _MANIFEST.actions if a.id == action_id)


def _with_card(key: Harness, action_id: str, args: dict[str, Any]) -> dict:
    return key.run_action(action_id, args)


def _without_card(key: Harness, action_id: str, args: dict[str, Any]) -> dict:
    return key.run_action(action_id, args, with_card=False, device="dev7")


def _expected(device_scoped: bool, **payload: Any) -> list[dict]:
    return [{"device": "dev7", **payload} if device_scoped else payload]


_ROUTES = pytest.mark.parametrize("route", [_with_card, _without_card], ids=["card", "device"])


def _scoped(route: Any) -> bool:
    return route is _without_card


@_ROUTES
@pytest.mark.parametrize("mode", ["next", "previous"])
@pytest.mark.parametrize("wrap", [True, False])
def test_page_next_and_previous_switch_with_wrap(key: Harness, route: Any, mode: str, wrap: bool) -> None:
    result = route(key, _PAGE, {"mode": mode, "wrap": wrap})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), to=mode, wrap=wrap))


@_ROUTES
def test_page_defaults_to_next_without_wrapping(key: Harness, route: Any) -> None:
    route(key, _PAGE, {})

    assert_that(key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), to="next", wrap=False))


@_ROUTES
def test_page_wrap_only_counts_when_exactly_true(key: Harness, route: Any) -> None:
    route(key, _PAGE, {"mode": "next", "wrap": "yes"})

    assert_that(key.sent_payloads("switch_page")[0]["wrap"]).is_false()


@_ROUTES
def test_page_mode_goes_to_the_chosen_page(key: Harness, route: Any) -> None:
    page = {"page_id": "p2", "name": "Settings", "index": 2, "profile_id": 0}

    result = route(key, _PAGE, {"mode": "page", "profile": {}, "page": page, "wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), page_id="p2"))


@_ROUTES
@pytest.mark.parametrize(
    "page",
    [_DELETED_PAGE, {"page_id": "", "name": "", "index": 0, "profile_id": -1}, {"page_id": "p1"}, None, "p1", 5],
)
def test_page_mode_without_a_live_page_is_an_error(key: Harness, route: Any, page: Any) -> None:
    result = route(key, _PAGE, {"mode": "page", "page": page})

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("the chosen page no longer exists")
    assert_that(key.sent_payloads("switch_page")).is_empty()


def test_page_navigation_without_card_or_device_is_an_error(key: Harness) -> None:
    result = key.run_action(_PAGE, {"mode": "next"}, with_card=False, device="")

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("no device for this call")
    assert_that(key.sent_payloads("switch_page")).is_empty()


def test_page_with_an_unknown_mode_is_an_error(key: Harness) -> None:
    result = key.run_action(_PAGE, {"mode": "sideways"})

    assert_that(result["ok"]).is_false()
    assert_that(key.sent_payloads("switch_page")).is_empty()


@_ROUTES
@pytest.mark.parametrize("mode", ["next", "previous"])
def test_profile_next_and_previous_switch_with_wrap(key: Harness, route: Any, mode: str) -> None:
    result = route(key, _PROFILE, {"mode": mode, "wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_profile")).is_equal_to(_expected(_scoped(route), to=mode, wrap=True))


@_ROUTES
def test_profile_defaults_to_next_without_wrapping(key: Harness, route: Any) -> None:
    route(key, _PROFILE, {})

    assert_that(key.sent_payloads("switch_profile")).is_equal_to(_expected(_scoped(route), to="next", wrap=False))


@_ROUTES
@pytest.mark.parametrize("profile_id", [0, 2])
def test_profile_mode_goes_to_the_chosen_profile(key: Harness, route: Any, profile_id: int) -> None:
    profile = {"profile_id": profile_id, "name": "Work", "index": 2, "icon": ""}

    result = route(key, _PROFILE, {"mode": "profile", "profile": profile})

    assert_that(result["ok"]).is_true()
    assert_that(key.sent_payloads("switch_profile")).is_equal_to(_expected(_scoped(route), profile_id=profile_id))


@_ROUTES
@pytest.mark.parametrize("profile", [_DELETED_PROFILE, None, "2", {"profile_id": True}, {"profile_id": "2"}])
def test_profile_mode_without_a_live_profile_is_an_error(key: Harness, route: Any, profile: Any) -> None:
    result = route(key, _PROFILE, {"mode": "profile", "profile": profile})

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("the chosen profile no longer exists")
    assert_that(key.sent_payloads("switch_profile")).is_empty()


def test_profile_navigation_without_card_or_device_is_an_error(key: Harness) -> None:
    result = key.run_action(_PROFILE, {"mode": "next"}, with_card=False, device="")

    assert_that(result["error"]).is_equal_to("no device for this call")
    assert_that(key.sent_payloads("switch_profile")).is_empty()


def test_a_card_in_the_call_wins_over_the_device(key: Harness) -> None:
    key.run_action(_PAGE, {"mode": "next"})

    assert_that(key.sent_payloads("switch_page")[0]).does_not_contain_key("device")


def test_page_action_settings() -> None:
    settings = {s.key: s for s in _spec(_PAGE).settings}

    assert_that(_spec(_PAGE).scope).is_equal_to("global")
    assert_that(list(settings)).is_equal_to(["mode", "profile", "page", "wrap"])
    assert_that([o["value"] for o in settings["mode"].extra["options"]]).is_equal_to(["page", "next", "previous"])
    assert_that(settings["mode"].default).is_equal_to("next")
    assert_that(settings["page"].extra["profile_field"]).is_equal_to("profile")
    assert_that(settings["wrap"].default).is_false()


def test_profile_action_settings() -> None:
    settings = {s.key: s for s in _spec(_PROFILE).settings}

    assert_that(_spec(_PROFILE).scope).is_equal_to("global")
    assert_that(list(settings)).is_equal_to(["mode", "profile", "wrap"])
    assert_that([o["value"] for o in settings["mode"].extra["options"]]).is_equal_to(["profile", "next", "previous"])
    assert_that(settings["mode"].default).is_equal_to("next")
    assert_that(settings["wrap"].default).is_false()
