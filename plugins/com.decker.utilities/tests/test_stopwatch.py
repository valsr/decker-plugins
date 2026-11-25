"""The Stopwatch: state machine, the card with its registry and ticker, and the actions."""

import base64
import io
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))
import stopwatch_card  # noqa: E402
import timers  # noqa: E402
from _harness import CONTEXT, PLUGIN_DIR, Harness, load_plugin  # noqa: E402
from stopwatch_card import Stopwatches  # noqa: E402
from timers import Stopwatch, fmt_ms  # noqa: E402

_CARD = "com.decker.utilities.stopwatch"
_TOGGLE = "com.decker.utilities.stopwatch-toggle"
_RESET = "com.decker.utilities.stopwatch-reset"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_WAIT = 5
_SIZE = 144


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(name="clock")
def clock_fixture() -> FakeClock:
    return FakeClock()


def wait_for(done: Callable[[], bool]) -> bool:
    stop = threading.Event()
    for _ in range(_WAIT * 100):
        if done():
            return True
        stop.wait(0.01)
    return done()


# --- Stopwatch state machine ---


def test_a_new_stopwatch_is_stopped_at_zero(clock: FakeClock) -> None:
    watch = Stopwatch(clock)

    assert_that(watch.running).is_false()
    assert_that(watch.elapsed()).is_equal_to(0)


def test_start_pause_resume_accumulates_only_the_running_time(clock: FakeClock) -> None:
    watch = Stopwatch(clock)

    watch.toggle()
    clock.now += 10
    assert_that(watch.elapsed()).is_equal_to(10)
    watch.toggle()
    clock.now += 100
    assert_that(watch.running).is_false()
    assert_that(watch.elapsed()).is_equal_to(10)
    watch.toggle()
    clock.now += 5
    assert_that(watch.running).is_true()
    assert_that(watch.elapsed()).is_equal_to(15)


@pytest.mark.parametrize("running", [False, True])
def test_reset_zeroes_and_stops(clock: FakeClock, running: bool) -> None:
    watch = Stopwatch(clock)
    watch.toggle()
    clock.now += 7
    if not running:
        watch.toggle()

    watch.reset()
    clock.now += 50

    assert_that(watch.running).is_false()
    assert_that(watch.elapsed()).is_equal_to(0)


def test_the_default_clock_is_the_sleep_inclusive_one() -> None:
    assert_that(Stopwatch()._clock).is_same_as(timers.sleep_inclusive_clock)  # noqa: SLF001


@pytest.mark.parametrize(("seconds", "text"), [(0, "0:00"), (65, "1:05"), (3600, "1:00:00")])
def test_the_face_text(seconds: float, text: str) -> None:
    assert_that(fmt_ms(seconds)).is_equal_to(text)


# --- the registry, on fakes ---


class FakeCanvas:
    def __init__(self, hook: Callable[[], None] | None = None) -> None:
        self.paints = 0
        self._hook = hook

    @contextmanager
    def paint(self) -> Iterator[Image.Image]:
        img = Image.new("RGBA", (_SIZE, _SIZE), (7, 7, 7, 255))  # a stale buffer: the card must clear it
        if self._hook is not None:
            self._hook()
        yield img
        self.paints += 1


class FakeCtx:
    def __init__(self, context: str = "k1") -> None:
        self.context = context
        self.settings: dict[str, Any] = {}
        self.canvas = FakeCanvas()


@pytest.fixture(name="texts")
def texts_fixture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = stopwatch_card.draw_time
    monkeypatch.setattr(stopwatch_card, "draw_time", lambda img, text: (seen.append(text), real(img, text))[1])
    return seen


@pytest.fixture(name="watches")
def watches_fixture(clock: FakeClock) -> Iterator[Stopwatches]:
    watches = Stopwatches(clock=clock, interval=3600)
    yield watches
    watches.stop()
    watches.clear()


def _track(watches: Stopwatches, context: str = "k1") -> FakeCtx:
    ctx = FakeCtx(context)
    watches.track(ctx)  # type: ignore[arg-type]
    return ctx


def test_a_new_key_shows_zero_on_a_cleared_buffer(watches: Stopwatches, texts: list[str]) -> None:
    ctx = _track(watches)

    assert_that(texts).is_equal_to(["0:00"])
    assert_that(ctx.canvas.paints).is_equal_to(1)


def test_toggle_paints_and_running_keys_repaint_each_tick(
    watches: Stopwatches, clock: FakeClock, texts: list[str]
) -> None:
    ctx = _track(watches)

    watches.toggle("k1")
    clock.now += 65
    watches.tick()

    assert_that(texts[-1]).is_equal_to("1:05")
    assert_that(ctx.canvas.paints).is_equal_to(3)


def test_stopped_keys_are_not_repainted_by_ticks(watches: Stopwatches, clock: FakeClock) -> None:
    ctx = _track(watches)
    watches.toggle("k1")
    watches.toggle("k1")
    paints = ctx.canvas.paints

    clock.now += 10
    watches.tick()

    assert_that(ctx.canvas.paints).is_equal_to(paints)


def test_reset_shows_zero(watches: Stopwatches, clock: FakeClock, texts: list[str]) -> None:
    _track(watches)
    watches.toggle("k1")
    clock.now += 30

    watches.reset("k1")

    assert_that(texts[-1]).is_equal_to("0:00")
    assert_that(watches.running("k1")).is_false()
    assert_that(watches.elapsed("k1")).is_equal_to(0)


def test_keys_are_independent(watches: Stopwatches, clock: FakeClock) -> None:
    _track(watches, "a")
    _track(watches, "b")

    watches.toggle("a")
    clock.now += 4

    assert_that(watches.elapsed("a")).is_equal_to(4)
    assert_that(watches.elapsed("b")).is_equal_to(0)


def test_it_survives_the_key_disappearing_and_the_return_repaints(
    watches: Stopwatches, clock: FakeClock, texts: list[str]
) -> None:
    ctx = _track(watches)
    watches.toggle("k1")

    watches.untrack(ctx)  # type: ignore[arg-type]
    clock.now += 90
    watches.tick()
    assert_that(watches.tracked("k1")).is_false()
    watches.track(ctx)  # type: ignore[arg-type]

    assert_that(watches.running("k1")).is_true()
    assert_that(texts[-1]).is_equal_to("1:30")


def test_a_toggle_with_no_prior_appear_creates_the_stopwatch(watches: Stopwatches, clock: FakeClock) -> None:
    watches.toggle("fresh")
    clock.now += 3

    assert_that(watches.running("fresh")).is_true()
    assert_that(watches.elapsed("fresh")).is_equal_to(3)


def test_reset_of_an_unknown_key_is_harmless(watches: Stopwatches) -> None:
    watches.reset("nope")

    assert_that(watches.running("nope")).is_false()


def test_concurrent_paints_of_one_key_leave_the_newest_time(
    watches: Stopwatches, clock: FakeClock, texts: list[str]
) -> None:
    gate, in_first = threading.Event(), threading.Event()
    ctx = FakeCtx()

    def hook() -> None:
        if not in_first.is_set():
            in_first.set()
            assert gate.wait(_WAIT)

    watches.toggle("k1")
    face = watches.track(ctx, paint=False)  # type: ignore[arg-type]
    ctx.canvas = FakeCanvas(hook)
    first = threading.Thread(target=watches.paint, args=(face,))
    first.start()
    assert in_first.wait(_WAIT)
    clock.now += 10
    second = threading.Thread(target=watches.paint, args=(face,))
    second.start()

    gate.set()
    first.join(_WAIT)
    second.join(_WAIT)

    assert_that(texts[-1]).is_equal_to("0:10")


# --- the ticker ---


def test_the_ticker_repaints_a_running_key_on_its_own(clock: FakeClock) -> None:
    watches = Stopwatches(clock=clock, interval=0.01)
    ctx = _track(watches)
    watches.toggle("k1")
    paints = ctx.canvas.paints
    watches.start_ticker()
    try:
        assert_that(wait_for(lambda: ctx.canvas.paints > paints)).is_true()
    finally:
        watches.stop()
        watches.clear()

    assert_that(watches.ticker_alive()).is_false()


def test_the_ticker_is_the_shared_helper_at_one_hertz() -> None:
    assert_that(stopwatch_card._watches._ticker._interval).is_equal_to(1.0)  # noqa: SLF001


# --- through the SDK loop ---


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="loop_watches")
def loop_watches_fixture(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[Stopwatches]:
    watches = Stopwatches(clock=clock, interval=3600)
    monkeypatch.setattr(stopwatch_card, "_watches", watches)
    yield watches
    watches.stop()
    watches.clear()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType, loop_watches: Stopwatches) -> Iterator[Harness]:
    harness = Harness(plugin, _CARD, "StopwatchCard")
    yield harness
    harness.close()


def _frame(key: Harness) -> Image.Image:
    payload = key.recv_until("set_image")["payload"]
    return Image.open(io.BytesIO(base64.b64decode(payload["image"]))).convert("RGBA")


def _run(key: Harness, action_id: str) -> dict:
    return key.run_action(action_id, {})


def test_the_key_paints_when_it_appears(key: Harness) -> None:
    key.appear({})

    assert_that(_frame(key).size).is_equal_to((_SIZE, _SIZE))


def test_toggle_and_reset_through_the_loop(key: Harness, loop_watches: Stopwatches, clock: FakeClock) -> None:
    key.appear({})
    _frame(key)

    assert_that(_run(key, _TOGGLE)).contains_entry({"ok": True})
    assert_that(loop_watches.running(CONTEXT)).is_true()
    assert_that(loop_watches.ticker_alive()).is_true()
    clock.now += 20
    assert_that(_run(key, _TOGGLE)).contains_entry({"ok": True})
    assert_that(loop_watches.running(CONTEXT)).is_false()
    assert_that(loop_watches.elapsed(CONTEXT)).is_equal_to(20)
    assert_that(_run(key, _RESET)).contains_entry({"ok": True})
    assert_that(loop_watches.elapsed(CONTEXT)).is_equal_to(0)


def test_page_switch_away_and_back_keeps_running(key: Harness, loop_watches: Stopwatches, clock: FakeClock) -> None:
    key.appear({})
    _frame(key)
    _run(key, _TOGGLE)

    key.send_event("will_disappear", {}, CONTEXT)
    assert_that(wait_for(lambda: not loop_watches.tracked(CONTEXT))).is_true()
    clock.now += 100
    key.appear({})

    assert_that(wait_for(lambda: loop_watches.tracked(CONTEXT))).is_true()
    assert_that(loop_watches.running(CONTEXT)).is_true()
    assert_that(loop_watches.elapsed(CONTEXT)).is_equal_to(100)


# --- manifest ---


def test_the_manifest_declares_the_card_and_actions() -> None:
    cards = {c.id: c for c in _MANIFEST.cards}
    actions = {a.id: a for a in _MANIFEST.actions}
    card = cards[_CARD]

    assert_that(card.icon).is_equal_to("fas:stopwatch")
    assert_that(card.bindings["press"].action).is_equal_to(_TOGGLE)
    assert_that(card.bindings["double_press"].action).is_equal_to(_RESET)
    assert_that(card.bindings["long_press"].action).is_equal_to(_RESET)
    assert_that(actions[_TOGGLE].scope).is_equal_to("plugin")
    assert_that(actions[_RESET].scope).is_equal_to("plugin")
