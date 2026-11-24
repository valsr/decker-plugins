"""Page and Profile: the global actions (through the card or the call's device) and the cards' faces."""

import base64
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.asset.renderer import AssetRenderer
from decker.common.model import PageInfo, ProfileInfo
from decker.plugin.manifest import PluginManifest
from decker.server.page_vars import DeviceLayout, deliver_settings
from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).parent))
from _harness import PLUGIN_DIR, Harness, load_plugin  # noqa: E402

_PAGE = "com.decker.utilities.page"
_PROFILE = "com.decker.utilities.profile"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_SIZE = 144
_RENDERER = AssetRenderer()
_PAGES = (("p1", "Home"), ("p2", "Settings"))
_PROFILES = ((0, "Default", ""), (2, "Work", "pack:a/b.svg"))
_DELETED_PAGE = {"page_id": "p9", "name": "", "index": 0, "profile_id": -1}
_DELETED_PROFILE = {"profile_id": -1, "name": "", "index": 0, "icon": ""}


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="page_key")
def page_key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _PAGE, "PageCard")
    yield harness
    harness.close()


@pytest.fixture(name="profile_key")
def profile_key_fixture(plugin: ModuleType):
    harness = Harness(plugin, _PROFILE, "ProfileCard")
    yield harness
    harness.close()


def _spec(action_id: str) -> Any:
    return next(a for a in _MANIFEST.actions if a.id == action_id)


def _page_bindings(**stored: Any) -> dict[str, Any]:
    """The bindings Decker sends a Page card: the stored press args resolved by Decker's own code."""
    infos = tuple(PageInfo(pid, name) for pid, name in _PAGES)
    layout = DeviceLayout(
        pages=infos,
        active_page_id="p1",
        profiles=(ProfileInfo(0, "Default"),),
        active_profile_id=0,
        pages_by_profile={0: infos},
    )
    values = {"mode": "next", "profile": "", "page": "", "wrap": False, **stored}
    return {"press": {"action": _PAGE, "args": deliver_settings(_spec(_PAGE).settings, values, layout, {})}}


def _profile_bindings(**stored: Any) -> dict[str, Any]:
    infos = tuple(ProfileInfo(pid, name, icon) for pid, name, icon in _PROFILES)
    layout = DeviceLayout(profiles=infos, active_profile_id=0)
    values = {"mode": "next", "profile": "", "wrap": False, **stored}
    return {"press": {"action": _PROFILE, "args": deliver_settings(_spec(_PROFILE).settings, values, layout, {})}}


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
def test_page_next_and_previous_switch_with_wrap(page_key: Harness, route: Any, mode: str, wrap: bool) -> None:
    result = route(page_key, _PAGE, {"mode": mode, "wrap": wrap})

    assert_that(result["ok"]).is_true()
    assert_that(page_key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), to=mode, wrap=wrap))


@_ROUTES
def test_page_defaults_to_next_without_wrapping(page_key: Harness, route: Any) -> None:
    route(page_key, _PAGE, {})

    assert_that(page_key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), to="next", wrap=False))


@_ROUTES
def test_page_wrap_only_counts_when_exactly_true(page_key: Harness, route: Any) -> None:
    route(page_key, _PAGE, {"mode": "next", "wrap": "yes"})

    assert_that(page_key.sent_payloads("switch_page")[0]["wrap"]).is_false()


@_ROUTES
def test_page_mode_goes_to_the_chosen_page(page_key: Harness, route: Any) -> None:
    page = {"page_id": "p2", "name": "Settings", "index": 2, "profile_id": 0}

    result = route(page_key, _PAGE, {"mode": "page", "profile": {}, "page": page, "wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(page_key.sent_payloads("switch_page")).is_equal_to(_expected(_scoped(route), page_id="p2"))


@_ROUTES
@pytest.mark.parametrize(
    "page",
    [_DELETED_PAGE, {"page_id": "", "name": "", "index": 0, "profile_id": -1}, {"page_id": "p1"}, None, "p1", 5],
)
def test_page_mode_without_a_live_page_is_an_error(page_key: Harness, route: Any, page: Any) -> None:
    result = route(page_key, _PAGE, {"mode": "page", "page": page})

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("the chosen page no longer exists")
    assert_that(page_key.sent_payloads("switch_page")).is_empty()


def test_page_navigation_without_card_or_device_is_an_error(page_key: Harness) -> None:
    result = page_key.run_action(_PAGE, {"mode": "next"}, with_card=False, device="")

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("no device for this call")
    assert_that(page_key.sent_payloads("switch_page")).is_empty()


def test_page_with_an_unknown_mode_is_an_error(page_key: Harness) -> None:
    result = page_key.run_action(_PAGE, {"mode": "sideways"})

    assert_that(result["ok"]).is_false()
    assert_that(page_key.sent_payloads("switch_page")).is_empty()


@_ROUTES
@pytest.mark.parametrize("mode", ["next", "previous"])
def test_profile_next_and_previous_switch_with_wrap(profile_key: Harness, route: Any, mode: str) -> None:
    result = route(profile_key, _PROFILE, {"mode": mode, "wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(profile_key.sent_payloads("switch_profile")).is_equal_to(_expected(_scoped(route), to=mode, wrap=True))


@_ROUTES
def test_profile_defaults_to_next_without_wrapping(profile_key: Harness, route: Any) -> None:
    route(profile_key, _PROFILE, {})

    assert_that(profile_key.sent_payloads("switch_profile")).is_equal_to(
        _expected(_scoped(route), to="next", wrap=False)
    )


@_ROUTES
@pytest.mark.parametrize("profile_id", [0, 2])
def test_profile_mode_goes_to_the_chosen_profile(profile_key: Harness, route: Any, profile_id: int) -> None:
    profile = {"profile_id": profile_id, "name": "Work", "index": 2, "icon": ""}

    result = route(profile_key, _PROFILE, {"mode": "profile", "profile": profile})

    assert_that(result["ok"]).is_true()
    assert_that(profile_key.sent_payloads("switch_profile")).is_equal_to(
        _expected(_scoped(route), profile_id=profile_id)
    )


@_ROUTES
@pytest.mark.parametrize("profile", [_DELETED_PROFILE, None, "2", {"profile_id": True}, {"profile_id": "2"}])
def test_profile_mode_without_a_live_profile_is_an_error(profile_key: Harness, route: Any, profile: Any) -> None:
    result = route(profile_key, _PROFILE, {"mode": "profile", "profile": profile})

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("the chosen profile no longer exists")
    assert_that(profile_key.sent_payloads("switch_profile")).is_empty()


def test_profile_navigation_without_card_or_device_is_an_error(profile_key: Harness) -> None:
    result = profile_key.run_action(_PROFILE, {"mode": "next"}, with_card=False, device="")

    assert_that(result["error"]).is_equal_to("no device for this call")
    assert_that(profile_key.sent_payloads("switch_profile")).is_empty()


def test_a_card_in_the_call_wins_over_the_device(page_key: Harness) -> None:
    page_key.run_action(_PAGE, {"mode": "next"})

    assert_that(page_key.sent_payloads("switch_page")[0]).does_not_contain_key("device")


def _svg(message: dict) -> bytes:
    payload = message["payload"]
    assert_that(payload["format"]).is_equal_to("svg")
    return base64.b64decode(payload["image"])


def _render(svg: bytes) -> Image.Image:
    layer = _RENDERER.render_bytes(svg, _SIZE, _SIZE)
    assert layer is not None
    return layer.convert("RGBA")


def _centre(message: dict) -> tuple[int, ...]:
    return _render(_svg(message)).getpixel((_SIZE // 2, _SIZE // 2))


def _ink_box(image: Image.Image) -> tuple[int, int, int, int]:
    box = image.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
    assert box is not None
    return box


def _color(**values: Any) -> dict[str, Any]:
    return {"color": "#ffffff", **values}


@pytest.mark.parametrize("key_name", ["page_key", "profile_key"])
def test_next_shows_a_caret_in_the_chosen_colour(request: pytest.FixtureRequest, key_name: str) -> None:
    key = request.getfixturevalue(key_name)
    bindings = _page_bindings() if key_name == "page_key" else _profile_bindings()

    key.appear(_color(color="#ff0000"), bindings)

    assert_that(_centre(key.recv_until("set_image"))).is_equal_to((255, 0, 0, 255))


def test_previous_is_the_mirrored_caret(page_key: Harness, profile_key: Harness) -> None:
    page_key.appear(_color(), _page_bindings(mode="next"))
    profile_key.appear(_color(), _profile_bindings(mode="previous"))

    right = _render(_svg(page_key.recv_until("set_image")))
    left = _render(_svg(profile_key.recv_until("set_image")))

    mirrored = left.transpose(Image.Transpose.FLIP_LEFT_RIGHT).getchannel("A")
    assert_that(left.tobytes()).is_not_equal_to(right.tobytes())
    assert_that(ImageStat.Stat(ImageChops.difference(mirrored, right.getchannel("A"))).mean[0]).is_less_than(2.0)


def test_caret_is_about_sixty_percent_of_the_key(page_key: Harness) -> None:
    page_key.appear(_color(), _page_bindings())

    left, top, right, bottom = _ink_box(_render(_svg(page_key.recv_until("set_image"))))

    assert_that((bottom - top) / _SIZE).is_between(0.55, 0.65)
    assert_that((top + bottom) / 2).is_between(_SIZE * 0.48, _SIZE * 0.52)
    assert_that((left + right) / 2).is_between(_SIZE * 0.45, _SIZE * 0.55)


def test_rgba_colour_has_partial_alpha(page_key: Harness) -> None:
    page_key.appear(_color(color="#ff000080"), _page_bindings())

    assert_that(_centre(page_key.recv_until("set_image"))[3]).is_between(110, 145)


@pytest.mark.parametrize("bad", [None, "red", "#12", 5])
def test_invalid_colours_fall_back_to_white(page_key: Harness, bad: Any) -> None:
    page_key.appear(_color(color=bad), _page_bindings())

    assert_that(_centre(page_key.recv_until("set_image"))).is_equal_to((255, 255, 255, 255))


def test_a_colour_change_redraws_the_caret(page_key: Harness) -> None:
    page_key.appear(_color(color="#ff0000"), _page_bindings())
    page_key.recv_until("set_image")

    page_key.change(_color(color="#00ff00"), _page_bindings())

    assert_that(_centre(page_key.recv_until("set_image"))).is_equal_to((0, 255, 0, 255))


def test_page_card_in_page_mode_shows_the_target_page_name(page_key: Harness) -> None:
    page_key.appear(_color(), _page_bindings(mode="page", page="p2"))

    assert_that(page_key.recv_until("set_image")["payload"]).is_equal_to({"image": None})
    assert_that(page_key.recv_until("set_title")["payload"]).is_equal_to({"title": "Settings"})


def test_page_card_follows_a_rebound_press(page_key: Harness) -> None:
    page_key.appear(_color(), _page_bindings(mode="page", page="p2"))
    page_key.recv_until("set_title")

    page_key.change(_color(), _page_bindings(mode="page", page="p1"))

    assert_that(page_key.recv_until("set_title")["payload"]).is_equal_to({"title": "Home"})


def test_page_card_going_from_a_page_to_a_caret_clears_the_title(page_key: Harness) -> None:
    page_key.appear(_color(), _page_bindings(mode="page", page="p2"))
    page_key.recv_until("set_title")

    page_key.change(_color(), _page_bindings(mode="next"))

    assert_that(_svg(page_key.recv_until("set_image"))).contains(b"<svg")
    assert_that(page_key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


@pytest.mark.parametrize(
    "bindings",
    [
        {},
        {"press": {"action": "com.decker.core.nothing"}},
        {"press": "x"},
        {"press": {"action": _PAGE, "args": {"mode": "sideways"}}},
        {"press": {"action": _PAGE, "args": {"mode": "page", "page": _DELETED_PAGE}}},
        {"press": {"action": _PAGE, "args": {"mode": "page", "page": None}}},
        {"press": {"action": _PROFILE, "args": {"mode": "next"}}},
    ],
)
def test_page_card_is_blank_without_a_usable_press_binding(page_key: Harness, bindings: Any) -> None:
    page_key.appear(_color(), bindings)

    assert_that(page_key.recv_until("set_image")["payload"]).is_equal_to({"image": None})
    assert_that(page_key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


def test_profile_card_in_profile_mode_shows_the_target_icon_and_name(profile_key: Harness) -> None:
    profile_key.appear(_color(), _profile_bindings(mode="profile", profile="2"))

    assert_that(profile_key.recv_until("set_image")["payload"]).is_equal_to({"icon": "pack:a/b.svg"})
    assert_that(profile_key.recv_until("set_title")["payload"]).is_equal_to({"title": "Work"})


def test_profile_zero_is_a_real_profile_on_the_face(profile_key: Harness) -> None:
    profile_key.appear(_color(), _profile_bindings(mode="profile", profile="0"))

    assert_that(profile_key.recv_until("set_title")["payload"]).is_equal_to({"title": "Default"})


def test_the_default_profile_shows_the_decker_icon(profile_key: Harness) -> None:
    profile_key.appear(_color(), _profile_bindings(mode="profile", profile="0"))

    assert_that(profile_key.recv_until("set_image")["payload"]).is_equal_to({"icon": "decker:logo"})


def test_a_profile_without_any_icon_ref_clears_the_image(profile_key: Harness) -> None:
    bindings = {
        "press": {"action": _PROFILE, "args": {"mode": "profile", "profile": {**_DELETED_PROFILE, "profile_id": 1}}}
    }

    profile_key.appear(_color(), bindings)

    assert_that(profile_key.recv_until("set_image")["payload"]).is_equal_to({"image": None})


def test_profile_card_going_from_a_profile_to_a_caret_clears_the_title(profile_key: Harness) -> None:
    profile_key.appear(_color(), _profile_bindings(mode="profile", profile="2"))
    profile_key.recv_until("set_title")

    profile_key.change(_color(), _profile_bindings(mode="next"))

    assert_that(profile_key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


@pytest.mark.parametrize(
    "bindings",
    [
        {},
        {"press": {"action": _PAGE, "args": {"mode": "next"}}},
        {"press": {"action": _PROFILE, "args": {"mode": "profile", "profile": _DELETED_PROFILE}}},
        {"press": {"action": _PROFILE, "args": {"mode": "profile", "profile": "2"}}},
    ],
)
def test_profile_card_is_blank_without_a_usable_press_binding(profile_key: Harness, bindings: Any) -> None:
    profile_key.appear(_color(), bindings)

    assert_that(profile_key.recv_until("set_image")["payload"]).is_equal_to({"image": None})
    assert_that(profile_key.recv_until("set_title")["payload"]).is_equal_to({"title": ""})


def test_names_with_braces_or_newlines_are_passed_through_as_text(page_key: Harness) -> None:
    bindings = {
        "press": {
            "action": _PAGE,
            "args": {"mode": "page", "page": {**_DELETED_PAGE, "name": "A {b}\nC", "profile_id": 0}},
        }
    }

    page_key.appear(_color(), bindings)

    assert_that(page_key.recv_until("set_title")["payload"]).is_equal_to({"title": "A {b}\nC"})


def _manifest_card(card_id: str) -> Any:
    return next(c for c in _MANIFEST.cards if c.id == card_id)


@pytest.mark.parametrize(("card_id", "mode"), [(_PAGE, "next"), (_PROFILE, "next")])
def test_cards_press_by_default_goes_to_the_next(card_id: str, mode: str) -> None:
    press = _manifest_card(card_id).bindings["press"]

    assert_that(press.action).is_equal_to(card_id)
    assert_that(press.args["mode"]).is_equal_to(mode)


def test_card_icons_and_colour_setting() -> None:
    assert_that(_manifest_card(_PAGE).icon).is_equal_to("fas:file")
    assert_that(_manifest_card(_PROFILE).icon).is_equal_to("fas:layer-group")
    for card_id in (_PAGE, _PROFILE):
        (colour,) = _manifest_card(card_id).settings
        assert_that((colour.key, colour.type, colour.default, colour.extra.get("alpha"))).is_equal_to(
            ("color", "color", "#ffffff", True)
        )


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
