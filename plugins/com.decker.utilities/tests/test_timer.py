"""The Timer: state machine, progress drawing, the card with its registry and ticker, and the actions."""

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
import timer_card  # noqa: E402
from _harness import CONTEXT, PLUGIN_DIR, Harness, load_plugin  # noqa: E402
from drawing import draw_progress, draw_time, progress_color  # noqa: E402
from timer_card import Timers  # noqa: E402
from timers import Timer, sleep_inclusive_clock  # noqa: E402

_CARD = "com.decker.utilities.timer"
_TOGGLE = "com.decker.utilities.timer-toggle"
_RESET = "com.decker.utilities.timer-reset"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_WAIT = 5
_SIZE = 144
_DEFAULTS: dict[str, Any] = {
    "minutes": 5,
    "seconds": 0,
    "show_time": True,
    "show_progress": True,
    "progress_type": "circle",
    "color_mode": "solid",
    "color": "#2ecc71",
    "color_2": "#e74c3c",
    "line_width": 6,
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(name="clock")
def clock_fixture() -> FakeClock:
    return FakeClock()


def wait_for(done: Callable[[], bool]) -> bool:
    """Poll a condition for a bounded time."""
    stop = threading.Event()
    for _ in range(_WAIT * 100):
        if done():
            return True
        stop.wait(0.01)
    return done()


# --- Timer state machine ---


def test_a_new_timer_is_idle_and_full(clock: FakeClock) -> None:
    timer = Timer(60, clock)

    assert_that(timer.state).is_equal_to("idle")
    assert_that(timer.remaining()).is_equal_to(60)
    assert_that(timer.fraction_left()).is_equal_to(1.0)
    assert_that(timer.tick()).is_false()


def test_toggle_starts_it_and_time_runs_down(clock: FakeClock) -> None:
    timer = Timer(60, clock)

    timer.toggle()
    clock.now += 15

    assert_that(timer.state).is_equal_to("running")
    assert_that(timer.remaining()).is_equal_to(45)
    assert_that(timer.fraction_left()).is_equal_to(0.75)


def test_toggle_pauses_freezes_and_resumes(clock: FakeClock) -> None:
    timer = Timer(60, clock)
    timer.toggle()
    clock.now += 20

    timer.toggle()
    clock.now += 100
    assert_that(timer.state).is_equal_to("paused")
    assert_that(timer.remaining()).is_equal_to(40)
    assert_that(timer.tick()).is_false()

    timer.toggle()
    clock.now += 10
    assert_that(timer.state).is_equal_to("running")
    assert_that(timer.remaining()).is_equal_to(30)


def test_tick_reports_the_finish_once(clock: FakeClock) -> None:
    timer = Timer(10, clock)
    timer.toggle()
    clock.now += 9.9
    assert_that(timer.tick()).is_false()

    clock.now += 0.2

    assert_that(timer.tick()).is_true()
    assert_that(timer.state).is_equal_to("finished")
    assert_that(timer.remaining()).is_equal_to(0)
    assert_that(timer.fraction_left()).is_equal_to(0.0)
    assert_that(timer.tick()).is_false()


def test_toggle_on_a_finished_timer_restarts_from_full(clock: FakeClock) -> None:
    timer = Timer(10, clock)
    timer.toggle()
    clock.now += 10
    timer.tick()

    timer.toggle()

    assert_that(timer.state).is_equal_to("running")
    assert_that(timer.remaining()).is_equal_to(10)


@pytest.mark.parametrize("steps", [0, 1, 2, 3])
def test_reset_goes_back_to_idle_and_full_from_any_state(clock: FakeClock, steps: int) -> None:
    timer = Timer(10, clock)
    for _ in range(min(steps, 2)):
        timer.toggle()
        clock.now += 4
    if steps == 3:
        clock.now += 10
        timer.tick()

    timer.reset()

    assert_that(timer.state).is_equal_to("idle")
    assert_that(timer.remaining()).is_equal_to(10)
    clock.now += 50
    assert_that(timer.remaining()).is_equal_to(10)


def test_a_timer_found_far_past_its_deadline_finishes_without_the_alarm(clock: FakeClock) -> None:
    timer = Timer(10, clock)
    timer.toggle()
    clock.now += 10 + 60  # the process stalled (or the clock kept counting through a system sleep)

    assert_that(timer.tick()).is_false()
    assert_that(timer.state).is_equal_to("finished")


def test_a_zero_duration_timer_has_nothing_left(clock: FakeClock) -> None:
    timer = Timer(0, clock)

    assert_that(timer.remaining()).is_equal_to(0)
    assert_that(timer.fraction_left()).is_equal_to(0.0)


# --- real time across a system sleep (the one clock keeps counting while the machine is suspended) ---


def test_the_sleep_inclusive_clock_is_a_non_decreasing_float() -> None:
    first = sleep_inclusive_clock()
    second = sleep_inclusive_clock()

    assert_that(first).is_instance_of(float)
    assert_that(second).is_greater_than_or_equal_to(first)


def test_a_timer_ending_during_a_system_sleep_finishes_quietly_at_zero(clock: FakeClock) -> None:
    timer = Timer(600, clock)
    timer.toggle()
    clock.now += 60
    clock.now += 3600  # the machine slept for an hour

    assert_that(timer.remaining()).is_equal_to(0)
    assert_that(timer.tick()).is_false()
    assert_that(timer.state).is_equal_to("finished")


def test_a_timer_with_time_left_after_a_short_sleep_shows_the_real_remaining_time(clock: FakeClock) -> None:
    timer = Timer(600, clock)
    timer.toggle()
    clock.now += 100
    clock.now += 200  # slept for 200 s

    assert_that(timer.remaining()).is_equal_to(300)
    assert_that(timer.tick()).is_false()
    assert_that(timer.state).is_equal_to("running")


def test_pause_and_resume_across_a_system_sleep_count_only_the_running_time(clock: FakeClock) -> None:
    timer = Timer(600, clock)
    timer.toggle()
    clock.now += 100
    timer.toggle()
    clock.now += 5000  # paused, and the machine slept
    timer.toggle()
    clock.now += 50
    clock.now += 100  # slept again while running

    assert_that(timer.remaining()).is_equal_to(350)


def test_the_registry_finishes_a_timer_that_ended_in_a_sleep_with_zero_and_no_alert(
    timers: Timers, clock: FakeClock, texts: list[str]
) -> None:
    ctx = _track(timers, minutes=1)
    timers.toggle("k1", 60)

    clock.now += 7200
    timers.tick()

    assert_that(timers.state("k1")).is_equal_to("finished")
    assert_that(texts[-1]).is_equal_to("0:00")
    assert_that(timers.pending_alerts()).is_equal_to(0)
    assert_that(ctx.alert_count).is_equal_to(0)


# --- progress_color ---


@pytest.mark.parametrize(
    ("mode", "fraction", "expected"),
    [
        ("solid", 1.0, "#ff0000"),
        ("solid", 0.0, "#ff0000"),
        ("bicolor", 1.0, "#ff0000"),
        ("bicolor", 0.5, "#ff0000"),
        ("bicolor", 0.2, "#0000ff"),
        ("bicolor", 0.0, "#0000ff"),
        ("gradient", 1.0, "#ff0000"),
        ("gradient", 0.5, "#800080"),
        ("gradient", 0.2, "#3300cc"),
        ("gradient", 0.0, "#0000ff"),
    ],
)
def test_progress_color(mode: Any, fraction: float, expected: str) -> None:
    assert_that(progress_color(mode, "#ff0000", "#0000ff", fraction)).is_equal_to(expected)


def test_progress_color_clamps_the_fraction() -> None:
    assert_that(progress_color("gradient", "#ff0000", "#0000ff", 1.5)).is_equal_to("#ff0000")
    assert_that(progress_color("gradient", "#ff0000", "#0000ff", -1)).is_equal_to("#0000ff")


# --- drawing ---


def _blank() -> Image.Image:
    return Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))


def _count(img: Image.Image, rgb: tuple[int, int, int], row: int) -> int:
    return sum(1 for x in range(_SIZE) if img.getpixel((x, row))[:3] == rgb and img.getpixel((x, row))[3] == 255)


def test_the_circle_starts_at_the_top_and_runs_clockwise() -> None:
    img = _blank()

    draw_progress(img, "circle", 0.5, "#2ecc71", 6)

    green = (46, 204, 113, 255)
    assert_that(img.getpixel((_SIZE // 2, 8))).is_equal_to(green)  # start of the arc, 12 o'clock
    assert_that(img.getpixel((_SIZE - 9, _SIZE // 2))).is_equal_to(green)  # 3 o'clock is inside the half
    assert_that(img.getpixel((_SIZE // 2, _SIZE - 9))).is_equal_to(green)  # 6 o'clock is its end
    assert_that(img.getpixel((8, _SIZE // 2))[3]).is_equal_to(0)  # 9 o'clock is already used up
    assert_that(img.getpixel((_SIZE // 2, _SIZE // 2))[3]).is_equal_to(0)  # a ring, not a disc


def test_a_full_circle_is_closed_and_an_empty_one_draws_nothing() -> None:
    full, empty = _blank(), _blank()

    draw_progress(full, "circle", 1.0, "#2ecc71", 6)
    draw_progress(empty, "circle", 0.0, "#2ecc71", 6)

    assert_that(full.getpixel((8, _SIZE // 2))[3]).is_equal_to(255)
    assert_that(full.getpixel((_SIZE // 2 - 1, 8))[3]).is_equal_to(255)
    assert_that(empty.getbbox()).is_none()


def test_the_bar_is_proportional_and_left_aligned() -> None:
    full, half = _blank(), _blank()
    draw_progress(full, "bar", 1.0, "#2ecc71", 6)
    box = full.getbbox()
    assert box is not None
    row = (box[1] + box[3]) // 2
    green = (46, 204, 113)

    draw_progress(half, "bar", 0.5, "#2ecc71", 6)

    assert_that(_count(half, green, row)).is_close_to(_count(full, green, row) / 2, 2)
    assert_that(half.getpixel((box[0], row))[:3]).is_equal_to(green)
    assert_that(half.getpixel((box[2] - 1, row))[3]).is_equal_to(0)


def test_a_wider_line_draws_more() -> None:
    thin, thick = _blank(), _blank()

    draw_progress(thin, "circle", 1.0, "#2ecc71", 2)
    draw_progress(thick, "circle", 1.0, "#2ecc71", 12)

    assert_that(thick.getpixel((_SIZE // 2, 20))[3]).is_equal_to(255)
    assert_that(thin.getpixel((_SIZE // 2, 20))[3]).is_equal_to(0)


def test_draw_time_writes_centred_text_and_nothing_for_an_empty_one() -> None:
    img, none = _blank(), _blank()

    draw_time(img, "4:59")
    draw_time(none, "")

    box = img.getbbox()
    assert box is not None
    assert_that((box[0] + box[2]) / 2).is_close_to(_SIZE / 2, 6)
    assert_that((box[1] + box[3]) / 2).is_close_to(_SIZE / 2, 8)
    assert_that(none.getbbox()).is_none()


def test_draw_time_shrinks_long_text_to_fit_the_key() -> None:
    img = _blank()

    draw_time(img, "10:00:00")

    box = img.getbbox()
    assert box is not None
    assert_that(box[0]).is_greater_than(0)
    assert_that(box[2]).is_less_than(_SIZE)


# --- the registry, on fakes ---


class FakeCanvas:
    def __init__(self, hook: Callable[[], None] | None = None) -> None:
        self.paints = 0
        self.frames: list[Image.Image] = []
        self._hook = hook

    @contextmanager
    def paint(self) -> Iterator[Image.Image]:
        img = Image.new("RGBA", (_SIZE, _SIZE), (7, 7, 7, 255))  # a stale buffer: the card must clear it
        if self._hook is not None:
            self._hook()
        yield img
        self.paints += 1
        self.frames.append(img.copy())


class FakeCtx:
    def __init__(self, settings: dict[str, Any] | None = None, context: str = "k1") -> None:
        self.context = context
        self.settings: dict[str, Any] = {**_DEFAULTS, **(settings or {})}
        self.canvas = FakeCanvas()
        self.alerts = threading.Semaphore(0)
        self.alert_count = 0

    def show_alert(self) -> None:
        self.alert_count += 1
        self.alerts.release()


@pytest.fixture(name="texts")
def texts_fixture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = timer_card.draw_time
    monkeypatch.setattr(timer_card, "draw_time", lambda img, text: (seen.append(text), real(img, text))[1])
    return seen


@pytest.fixture(name="timers")
def timers_fixture(clock: FakeClock) -> Iterator[Timers]:
    timers = Timers(clock=clock, interval=3600, alert_delay=0.0)
    yield timers
    timers.stop()
    timers.clear()


def _track(timers: Timers, **settings: Any) -> FakeCtx:
    ctx = FakeCtx(settings)
    timers.track(ctx)  # type: ignore[arg-type]
    return ctx


def test_an_idle_key_shows_the_full_duration(timers: Timers, texts: list[str]) -> None:
    ctx = _track(timers, minutes=1, seconds=30)

    assert_that(texts).is_equal_to(["1:30"])
    assert_that(timers.state("k1")).is_equal_to("idle")
    assert_that(ctx.canvas.paints).is_equal_to(1)


def test_painting_clears_the_buffer_first(timers: Timers) -> None:
    ctx = _track(timers, show_progress=False, show_time=False)

    assert_that(ctx.canvas.frames[0].getbbox()).is_none()


def test_show_time_and_show_progress_switch_the_parts_off(timers: Timers, texts: list[str]) -> None:
    ctx = _track(timers, show_time=False, show_progress=False)
    assert_that(texts).is_empty()

    timers.settings_changed(_with(ctx, show_progress=True))

    assert_that(ctx.canvas.frames[-1].getbbox()).is_not_none()
    assert_that(texts).is_empty()


def _with(ctx: FakeCtx, **settings: Any) -> FakeCtx:
    ctx.settings = {**ctx.settings, **settings}
    return ctx


def test_a_running_timer_repaints_every_tick_with_the_time_left(
    timers: Timers, clock: FakeClock, texts: list[str]
) -> None:
    ctx = _track(timers, minutes=1)
    timers.toggle("k1", 60)

    clock.now += 1
    timers.tick()
    clock.now += 1.5
    timers.tick()

    assert_that(texts).is_equal_to(["1:00", "1:00", "0:59", "0:58"])
    assert_that(ctx.canvas.paints).is_equal_to(4)


def test_idle_paused_and_finished_keys_are_not_repainted_by_ticks(timers: Timers, clock: FakeClock) -> None:
    ctx = _track(timers, minutes=0, seconds=10)
    timers.tick()
    assert_that(ctx.canvas.paints).is_equal_to(1)  # idle

    timers.toggle("k1", 10)
    timers.toggle("k1", 10)
    paused = ctx.canvas.paints
    clock.now += 3
    timers.tick()
    timers.tick()
    assert_that(ctx.canvas.paints).is_equal_to(paused)

    timers.toggle("k1", 10)
    clock.now += 10
    timers.tick()
    assert_that(timers.state("k1")).is_equal_to("finished")
    done = ctx.canvas.paints
    timers.tick()
    timers.tick()
    assert_that(ctx.canvas.paints).is_equal_to(done)


def test_finishing_shows_zero_and_alerts_three_times(timers: Timers, clock: FakeClock, texts: list[str]) -> None:
    ctx = _track(timers, minutes=0, seconds=5)
    timers.toggle("k1", 5)

    clock.now += 5
    timers.tick()

    assert_that(texts[-1]).is_equal_to("0:00")
    for _ in range(3):
        assert_that(ctx.alerts.acquire(timeout=_WAIT)).is_true()
    assert_that(wait_for(lambda: timers.pending_alerts() == 0)).is_true()
    assert_that(ctx.alert_count).is_equal_to(3)
    timers.tick()
    assert_that(ctx.alert_count).is_equal_to(3)


def test_the_alerts_are_spaced_by_the_delay_off_the_ticking_thread(clock: FakeClock) -> None:
    timers = Timers(clock=clock, interval=3600, alert_delay=3600)
    try:
        ctx = _track(timers, minutes=0, seconds=5)
        timers.toggle("k1", 5)
        clock.now += 5

        timers.tick()  # returns although the next alerts are an hour away

        assert_that(ctx.alerts.acquire(timeout=_WAIT)).is_true()
        assert_that(timers.pending_alerts()).is_equal_to(1)
        timers.reset("k1")
        assert_that(wait_for(lambda: timers.pending_alerts() == 0)).is_true()
        assert_that(ctx.alert_count).is_equal_to(1)
    finally:
        timers.stop()
        timers.clear()


def test_a_restart_during_the_alerts_cancels_the_rest(clock: FakeClock) -> None:
    timers = Timers(clock=clock, interval=3600, alert_delay=3600)
    try:
        ctx = _track(timers, minutes=0, seconds=5)
        timers.toggle("k1", 5)
        clock.now += 5
        timers.tick()
        assert_that(ctx.alerts.acquire(timeout=_WAIT)).is_true()

        timers.toggle("k1", 5)

        assert_that(wait_for(lambda: timers.pending_alerts() == 0)).is_true()
        assert_that(ctx.alert_count).is_equal_to(1)
        assert_that(timers.state("k1")).is_equal_to("running")
    finally:
        timers.stop()
        timers.clear()


def test_a_timer_found_far_past_its_deadline_finishes_silently(timers: Timers, clock: FakeClock) -> None:
    ctx = _track(timers, minutes=0, seconds=5)
    timers.toggle("k1", 5)

    clock.now += 600
    timers.tick()

    assert_that(timers.state("k1")).is_equal_to("finished")
    assert_that(timers.pending_alerts()).is_equal_to(0)
    assert_that(ctx.alert_count).is_equal_to(0)


@pytest.mark.parametrize("state", ["running", "paused"])
def test_changing_the_duration_resets_to_idle_with_the_new_duration(
    timers: Timers, clock: FakeClock, texts: list[str], state: str
) -> None:
    ctx = _track(timers, minutes=5)
    timers.toggle("k1", 300)
    clock.now += 10
    if state == "paused":
        timers.toggle("k1", 300)

    timers.settings_changed(_with(ctx, minutes=2, seconds=30))

    assert_that(timers.state("k1")).is_equal_to("idle")
    assert_that(timers.remaining("k1")).is_equal_to(150)
    assert_that(texts[-1]).is_equal_to("2:30")


def test_changing_a_cosmetic_setting_keeps_the_running_timer(timers: Timers, clock: FakeClock) -> None:
    ctx = _track(timers, minutes=5)
    timers.toggle("k1", 300)
    clock.now += 10

    timers.settings_changed(_with(ctx, color="#ff00ff", progress_type="bar"))

    assert_that(timers.state("k1")).is_equal_to("running")
    assert_that(timers.remaining("k1")).is_equal_to(290)


def test_a_timer_survives_the_key_disappearing_and_the_return_shows_the_time_left(
    timers: Timers, clock: FakeClock, texts: list[str]
) -> None:
    ctx = _track(timers, minutes=2)
    timers.toggle("k1", 120)
    timers.untrack(ctx)  # type: ignore[arg-type]

    clock.now += 30
    timers.tick()
    again = _track(timers, minutes=2)

    assert_that(timers.state("k1")).is_equal_to("running")
    assert_that(texts[-1]).is_equal_to("1:30")
    assert_that(again.canvas.paints).is_equal_to(1)
    assert_that(ctx.canvas.paints).is_equal_to(2)  # nothing was drawn on the old key while it was away


def test_a_return_after_a_duration_change_while_away_starts_idle(timers: Timers, clock: FakeClock) -> None:
    ctx = _track(timers, minutes=2)
    timers.toggle("k1", 120)
    timers.untrack(ctx)  # type: ignore[arg-type]

    _track(timers, minutes=3)

    assert_that(timers.state("k1")).is_equal_to("idle")
    assert_that(timers.remaining("k1")).is_equal_to(180)


def test_a_toggle_with_no_prior_appear_creates_the_timer(timers: Timers, clock: FakeClock) -> None:
    assert_that(timers.state("nope")).is_equal_to("idle")

    timers.toggle("nope", 30)
    clock.now += 5

    assert_that(timers.state("nope")).is_equal_to("running")
    assert_that(timers.remaining("nope")).is_equal_to(25)


def test_reset_of_an_unknown_key_is_harmless(timers: Timers) -> None:
    timers.reset("nope")

    assert_that(timers.state("nope")).is_equal_to("idle")


def test_concurrent_paints_of_one_key_leave_the_newest_time(timers: Timers, clock: FakeClock, texts: list[str]) -> None:
    gate, in_first = threading.Event(), threading.Event()
    ctx = FakeCtx({"minutes": 1})

    def hook() -> None:
        if not in_first.is_set():
            in_first.set()
            assert gate.wait(_WAIT)

    timers.toggle("k1", 60)
    face = timers.track(ctx, paint=False)  # type: ignore[arg-type]
    ctx.canvas = FakeCanvas(hook)
    first = threading.Thread(target=timers.paint, args=(face,))
    first.start()
    assert in_first.wait(_WAIT)
    clock.now += 10
    second = threading.Thread(target=timers.paint, args=(face,))
    second.start()

    gate.set()
    first.join(_WAIT)
    second.join(_WAIT)

    assert_that(texts[-1]).is_equal_to("0:50")


# --- the ticker ---


def test_the_ticker_finishes_a_timer_on_its_own(clock: FakeClock) -> None:
    timers = Timers(clock=clock, interval=0.01, alert_delay=0.0)
    ctx = _track(timers, minutes=0, seconds=5)
    timers.toggle("k1", 5)
    clock.now += 5
    timers.start_ticker()
    try:
        assert_that(ctx.alerts.acquire(timeout=_WAIT)).is_true()
    finally:
        timers.stop()

    assert_that(timers.state("k1")).is_equal_to("finished")
    assert_that(timers.ticker_alive()).is_false()


def test_the_ticker_is_the_shared_helper_at_four_hertz() -> None:
    assert_that(timer_card._timers._ticker._interval).is_equal_to(0.25)  # noqa: SLF001


# --- through the SDK loop ---


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="loop_timers")
def loop_timers_fixture(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[Timers]:
    timers = Timers(clock=clock, interval=3600, alert_delay=0.0)
    monkeypatch.setattr(timer_card, "_timers", timers)
    yield timers
    timers.stop()
    timers.clear()


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType, loop_timers: Timers) -> Iterator[Harness]:
    harness = Harness(plugin, _CARD, "TimerCard")
    yield harness
    harness.close()


def _frame(key: Harness) -> Image.Image:
    payload = key.recv_until("set_image")["payload"]
    return Image.open(io.BytesIO(base64.b64decode(payload["image"]))).convert("RGBA")


def _run(key: Harness, action_id: str) -> dict:
    return key.run_action(action_id, {})


def test_the_key_shows_the_full_ring_when_it_appears(key: Harness) -> None:
    key.appear(_DEFAULTS)

    frame = _frame(key)

    assert_that(frame.size).is_equal_to((_SIZE, _SIZE))
    assert_that(frame.getpixel((_SIZE // 2, 8))[:3]).is_equal_to((46, 204, 113))


def test_toggle_starts_and_pauses_and_reset_goes_idle(key: Harness, loop_timers: Timers, clock: FakeClock) -> None:
    key.appear(_DEFAULTS)
    _frame(key)

    assert_that(_run(key, _TOGGLE)).contains_entry({"ok": True})
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("running")
    clock.now += 60
    assert_that(_run(key, _TOGGLE)).contains_entry({"ok": True})
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("paused")
    assert_that(loop_timers.remaining(CONTEXT)).is_equal_to(240)
    assert_that(_run(key, _RESET)).contains_entry({"ok": True})
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("idle")
    assert_that(loop_timers.remaining(CONTEXT)).is_equal_to(300)


def test_the_first_toggle_starts_the_ticker(key: Harness, loop_timers: Timers) -> None:
    key.appear(_DEFAULTS)
    _frame(key)
    assert_that(loop_timers.ticker_alive()).is_false()

    _run(key, _TOGGLE)

    assert_that(loop_timers.ticker_alive()).is_true()


def test_zero_duration_shows_zero_and_refuses_to_start(key: Harness, loop_timers: Timers) -> None:
    key.appear({**_DEFAULTS, "minutes": 0, "seconds": 0, "show_progress": False})
    _frame(key)

    result = _run(key, _TOGGLE)

    assert_that(result).contains_entry({"ok": False})
    assert_that(result["error"]).contains("set a duration")
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("idle")
    assert_that([m for m in key.sent if m["event"] == "show_alert"]).is_length(1)


def test_changing_minutes_in_the_settings_resets_a_running_timer(
    key: Harness, loop_timers: Timers, clock: FakeClock
) -> None:
    key.appear(_DEFAULTS)
    _frame(key)
    _run(key, _TOGGLE)
    clock.now += 30

    key.change({**_DEFAULTS, "minutes": 1})

    assert_that(wait_for(lambda: loop_timers.state(CONTEXT) == "idle")).is_true()
    assert_that(loop_timers.remaining(CONTEXT)).is_equal_to(60)


def test_a_finishing_timer_alerts_three_times_through_the_loop(
    key: Harness, loop_timers: Timers, clock: FakeClock
) -> None:
    key.appear({**_DEFAULTS, "minutes": 0, "seconds": 5})
    _frame(key)
    _run(key, _TOGGLE)
    clock.now += 5

    loop_timers.tick()

    for _ in range(3):
        key.recv_until("show_alert")
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("finished")


def test_page_switch_away_and_back_keeps_running(key: Harness, loop_timers: Timers, clock: FakeClock) -> None:
    key.appear(_DEFAULTS)
    _frame(key)
    _run(key, _TOGGLE)

    key.send_event("will_disappear", {}, CONTEXT)
    assert_that(wait_for(lambda: not loop_timers.tracked(CONTEXT))).is_true()
    clock.now += 100
    loop_timers.tick()
    key.appear(_DEFAULTS)

    assert_that(wait_for(lambda: loop_timers.tracked(CONTEXT))).is_true()
    assert_that(loop_timers.state(CONTEXT)).is_equal_to("running")
    assert_that(loop_timers.remaining(CONTEXT)).is_equal_to(200)


# --- manifest ---


def test_the_manifest_declares_the_card_and_actions() -> None:
    cards = {c.id: c for c in _MANIFEST.cards}
    actions = {a.id: a for a in _MANIFEST.actions}
    card = cards[_CARD]
    fields = {s.key: s for s in card.settings}

    assert_that(card.icon).is_equal_to("fas:stopwatch")
    assert_that(card.bindings["press"].action).is_equal_to(_TOGGLE)
    assert_that(card.bindings["double_press"].action).is_equal_to(_RESET)
    assert_that(card.bindings["long_press"].action).is_equal_to(_RESET)
    assert_that(actions[_TOGGLE].scope).is_equal_to("plugin")
    assert_that(actions[_RESET].scope).is_equal_to("plugin")
    assert_that({k: f.default for k, f in fields.items()}).is_equal_to(_DEFAULTS)
    assert_that({k: f.type for k, f in fields.items()}).is_equal_to(
        {
            "minutes": "int",
            "seconds": "int",
            "show_time": "bool",
            "show_progress": "bool",
            "progress_type": "choice",
            "color_mode": "choice",
            "color": "color",
            "color_2": "color",
            "line_width": "int",
        }
    )
    assert_that((fields["minutes"].extra["min"], fields["minutes"].extra["max"])).is_equal_to((0, 1440))
    assert_that((fields["seconds"].extra["min"], fields["seconds"].extra["max"])).is_equal_to((0, 59))
    assert_that((fields["line_width"].extra["min"], fields["line_width"].extra["max"])).is_equal_to((1, 20))
    assert_that([o["value"] for o in fields["progress_type"].extra["options"]]).is_equal_to(["circle", "bar"])
    assert_that([o["value"] for o in fields["color_mode"].extra["options"]]).is_equal_to(
        ["solid", "bicolor", "gradient"]
    )
