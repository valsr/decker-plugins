"""Next and Previous keys: the recoloured caret and the switch_profile request."""

import base64
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.asset.renderer import AssetRenderer
from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).parent))
from _profiles_harness import PLUGIN_DIR, Harness, load_plugin  # noqa: E402

_NEXT = "com.decker.profiles.next"
_PREVIOUS = "com.decker.profiles.previous"
_SIZE = 144
_RENDERER = AssetRenderer()


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="next_key")
def next_fixture(plugin: ModuleType):
    harness = Harness(plugin, _NEXT, "NextCard")
    yield harness
    harness.close()


@pytest.fixture(name="previous_key")
def previous_fixture(plugin: ModuleType):
    harness = Harness(plugin, _PREVIOUS, "PreviousCard")
    yield harness
    harness.close()


def _settings(**values: Any) -> dict[str, Any]:
    return {"color": "#ffffff", **values}


def _svg(message: dict) -> bytes:
    payload = message["payload"]
    assert_that(payload["format"]).is_equal_to("svg")
    return base64.b64decode(payload["image"])


def _render(svg: bytes) -> Image.Image:
    layer = _RENDERER.render_bytes(svg, _SIZE, _SIZE)
    assert layer is not None
    return layer.convert("RGBA")


def _ink_box(image: Image.Image) -> tuple[int, int, int, int]:
    box = image.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
    assert box is not None
    return box


def test_next_shows_the_right_caret_in_the_chosen_colour(next_key: Harness) -> None:
    next_key.appear(_settings(color="#ff0000"))

    image = _render(_svg(next_key.recv_until("set_image")))

    assert_that(image.getpixel((_SIZE // 2, _SIZE // 2))).is_equal_to((255, 0, 0, 255))


def test_previous_shows_the_left_caret(next_key: Harness, previous_key: Harness) -> None:
    next_key.appear(_settings())
    previous_key.appear(_settings())

    right = _render(_svg(next_key.recv_until("set_image")))
    left = _render(_svg(previous_key.recv_until("set_image")))

    assert_that(left.tobytes()).is_not_equal_to(right.tobytes())
    mirrored = left.transpose(Image.Transpose.FLIP_LEFT_RIGHT).getchannel("A")
    difference = ImageStat.Stat(ImageChops.difference(mirrored, right.getchannel("A"))).mean[0]
    assert_that(difference).is_less_than(2.0)  # mirrored, up to one pixel of antialiasing


def test_default_colour_is_visible_on_black(next_key: Harness) -> None:
    next_key.appear(_settings())

    image = _render(_svg(next_key.recv_until("set_image")))

    assert_that(image.getpixel((_SIZE // 2, _SIZE // 2))[:3]).is_equal_to((255, 255, 255))


def test_rgba_colour_has_partial_alpha(next_key: Harness) -> None:
    next_key.appear(_settings(color="#ff000080"))

    alpha = _render(_svg(next_key.recv_until("set_image"))).getpixel((_SIZE // 2, _SIZE // 2))[3]

    assert_that(alpha).is_between(110, 145)


def test_caret_is_about_sixty_percent_of_the_key(next_key: Harness) -> None:
    next_key.appear(_settings())

    left, top, right, bottom = _ink_box(_render(_svg(next_key.recv_until("set_image"))))

    assert_that((bottom - top) / _SIZE).is_between(0.55, 0.65)
    assert_that((top + bottom) / 2).is_between(_SIZE * 0.48, _SIZE * 0.52)
    assert_that((left + right) / 2).is_between(_SIZE * 0.45, _SIZE * 0.55)


@pytest.mark.parametrize("bad", [None, "red", "#12", 5])
def test_invalid_colours_fall_back_to_white(next_key: Harness, bad: Any) -> None:
    next_key.appear(_settings(color=bad))

    image = _render(_svg(next_key.recv_until("set_image")))

    assert_that(image.getpixel((_SIZE // 2, _SIZE // 2))).is_equal_to((255, 255, 255, 255))


def test_settings_changed_redraws_with_the_new_colour(next_key: Harness) -> None:
    next_key.appear(_settings(color="#ff0000"))
    next_key.recv_until("set_image")

    next_key.change(_settings(color="#00ff00"))

    image = _render(_svg(next_key.recv_until("set_image")))
    assert_that(image.getpixel((_SIZE // 2, _SIZE // 2))).is_equal_to((0, 255, 0, 255))


def test_next_action_switches_the_card_device_profile_with_wrap(next_key: Harness) -> None:
    result = next_key.run_action(_NEXT, {"wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(next_key.sent_payloads("switch_profile")).is_equal_to(
        [{"to": "next", "wrap": True, "request": next_key.request}]
    )


def test_next_action_does_not_wrap_by_default(next_key: Harness) -> None:
    next_key.run_action(_NEXT, {"wrap": False})

    assert_that(next_key.sent_payloads("switch_profile")).is_equal_to(
        [{"to": "next", "wrap": False, "request": next_key.request}]
    )


@pytest.mark.parametrize("wrap", ["yes", 1, None])
def test_only_true_counts_as_wrap(next_key: Harness, wrap: Any) -> None:
    next_key.run_action(_NEXT, {"wrap": wrap})

    assert_that(next_key.sent_payloads("switch_profile")[0]["wrap"]).is_false()


def test_previous_action(previous_key: Harness) -> None:
    result = previous_key.run_action(_PREVIOUS, {"wrap": False})

    assert_that(result["ok"]).is_true()
    assert_that(previous_key.sent_payloads("switch_profile")).is_equal_to(
        [{"to": "previous", "wrap": False, "request": previous_key.request}]
    )


def test_action_run_by_an_appeared_card_uses_its_own_key(next_key: Harness) -> None:
    next_key.appear(_settings(), {"press": {"action": _NEXT, "args": {"wrap": True}}})
    next_key.recv_until("set_image")

    result = next_key.run_action(_NEXT, {"wrap": True})

    assert_that(result["ok"]).is_true()
    assert_that(next_key.sent_payloads("switch_profile")).is_equal_to([{"to": "next", "wrap": True}])
    assert_that(next_key.sent_payloads("switch_profile")[0]).does_not_contain_key("request")


@pytest.mark.parametrize("action_id", [_NEXT, _PREVIOUS])
def test_actions_without_a_card_fail(next_key: Harness, action_id: str) -> None:
    result = next_key.run_action(action_id, {"wrap": False}, with_card=False)

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).is_equal_to("needs a card")
    assert_that(next_key.sent_payloads("switch_profile")).is_empty()


def test_render_caret_leaves_other_svg_content_alone(plugin: ModuleType) -> None:
    source = (PLUGIN_DIR / "assets" / "caret-right.svg").read_bytes().decode()

    out = plugin.render_caret(source.encode(), "#336699").decode()

    body = lambda text: text[text.index(">") + 1 :]  # noqa: E731
    assert_that(body(out)).is_equal_to(body(source).replace("currentColor", "#336699"))
    assert_that(re.search(r'viewBox="([^"]+)"', out)).is_not_none()
