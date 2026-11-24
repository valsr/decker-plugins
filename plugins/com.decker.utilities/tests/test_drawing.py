"""Drawing helpers: the level-to-grey mapping, the tinted icon and the caption."""

import io
import sys
from pathlib import Path

import pytest
from assertpy import assert_that
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from drawing import draw_caption, draw_icon, level_grey  # noqa: E402

_SIZE = 144


def _white_square_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _blank() -> Image.Image:
    return Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))


@pytest.mark.parametrize(("percent", "expected"), [(100, "#ffffff"), (0, "#000000"), (50, "#808080"), (25, "#404040")])
def test_level_grey_is_linear_from_black_to_white(percent: int, expected: str) -> None:
    assert_that(level_grey(percent)).is_equal_to(expected)


def test_level_grey_clamps_out_of_range_levels() -> None:
    assert_that(level_grey(-5)).is_equal_to("#000000")
    assert_that(level_grey(180)).is_equal_to("#ffffff")


def test_draw_icon_tints_the_icon_and_leaves_the_corners_clear() -> None:
    img = _blank()

    draw_icon(img, _white_square_png(), "#ff0000")

    assert_that(img.getpixel((_SIZE // 2, _SIZE // 2))).is_equal_to((255, 0, 0, 255))
    assert_that(img.getpixel((2, 2))[3]).is_equal_to(0)


def test_draw_icon_keeps_the_icon_transparency() -> None:
    src = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    src.paste((255, 255, 255, 255), (0, 0, 20, 40))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    img = _blank()

    draw_icon(img, buf.getvalue(), "#00ff00")

    assert_that(img.getpixel((_SIZE // 2 - 10, _SIZE // 2))[3]).is_equal_to(255)
    assert_that(img.getpixel((_SIZE // 2 + 10, _SIZE // 2))[3]).is_equal_to(0)


def test_draw_icon_rejects_a_bad_colour() -> None:
    with pytest.raises(ValueError):
        draw_icon(_blank(), _white_square_png(), "not-a-colour")


def test_draw_caption_draws_near_the_bottom_centre() -> None:
    img = _blank()

    draw_caption(img, "75%")

    box = img.getbbox()
    assert_that(box).is_not_none()
    assert_that((box[1] + box[3]) / 2).is_greater_than(_SIZE * 0.6)
    assert_that((box[0] + box[2]) / 2).is_close_to(_SIZE / 2, 6)


def test_draw_caption_with_no_text_draws_nothing() -> None:
    img = _blank()

    draw_caption(img, "")

    assert_that(img.getbbox()).is_none()
