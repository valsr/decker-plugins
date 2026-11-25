"""The shared key registry, through a minimal subclass."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
from key_registry import KeyRegistry  # noqa: E402


class _Canvas:
    def __init__(self) -> None:
        self.paints = 0

    @contextmanager
    def paint(self) -> Iterator[Image.Image]:
        img = Image.new("RGBA", (4, 4), (9, 9, 9, 255))
        yield img
        self.paints += 1
        self.last = img


class _Ctx:
    def __init__(self, context: str = "k1") -> None:
        self.context = context
        self.settings: dict[str, Any] = {}
        self.canvas = _Canvas()


class _Registry(KeyRegistry[int]):
    def _prepare(self, ctx: Any) -> None:
        self._items.setdefault(ctx.context, 0)

    def _snapshot(self, ctx: Any) -> int:
        return self._items[ctx.context]

    def _draw(self, img: Any, settings: dict[str, Any], snapshot: int) -> None:
        img.putpixel((0, 0), (snapshot, 0, 0, 255))

    def tick(self) -> None:
        pass


@pytest.fixture(name="registry")
def registry_fixture() -> Iterator[_Registry]:
    registry = _Registry(3600, "test-ticker")
    yield registry
    registry.stop()


def test_track_paints_a_cleared_buffer_and_remembers_the_key(registry: _Registry) -> None:
    ctx = _Ctx()
    registry.track(ctx)  # type: ignore[arg-type]

    assert_that(registry.tracked("k1")).is_true()
    assert_that(ctx.canvas.paints).is_equal_to(1)
    assert_that(ctx.canvas.last.getpixel((3, 3))).is_equal_to((0, 0, 0, 0))


def test_tracking_again_keeps_the_face_and_takes_the_new_context(registry: _Registry) -> None:
    first, second = _Ctx(), _Ctx()
    face = registry.track(first, paint=False)  # type: ignore[arg-type]

    assert_that(registry.track(second, paint=False)).is_same_as(face)  # type: ignore[arg-type]
    assert_that(face.ctx).is_same_as(second)
    assert_that(first.canvas.paints).is_equal_to(0)


def test_untrack_and_clear_forget_keys(registry: _Registry) -> None:
    a, b = _Ctx("a"), _Ctx("b")
    registry.track(a)  # type: ignore[arg-type]
    registry.track(b)  # type: ignore[arg-type]

    registry.untrack(a)  # type: ignore[arg-type]
    assert_that(registry.tracked("a")).is_false()
    registry.clear()

    assert_that(registry.tracked("b")).is_false()


def test_the_ticker_is_lazy_and_stops(registry: _Registry) -> None:
    assert_that(registry.ticker_alive()).is_false()
    registry.start_ticker()
    assert_that(registry.ticker_alive()).is_true()
    registry.stop()

    assert_that(registry.ticker_alive()).is_false()
