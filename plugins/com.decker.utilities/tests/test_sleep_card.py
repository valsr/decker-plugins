"""The Sleep card, its actions and the countdown registry: unit tests on a fake clock, plus the SDK loop."""

import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))
import power  # noqa: E402
import sleep_card  # noqa: E402
from _harness import CONTEXT, PLUGIN_DIR, Harness, load_plugin  # noqa: E402
from power import PowerError  # noqa: E402
from sleep_card import Sleeper  # noqa: E402
from timers import Countdown, fmt_ms  # noqa: E402

_CARD = "com.decker.utilities.sleep"
_PRESS = "com.decker.utilities.sleep-press"
_AFTER = "com.decker.utilities.sleep-after"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_WAIT = 5


class FakeClock:
    """A sleep-inclusive clock: a system sleep is just time passing on it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeCtx:
    """The parts of a CardContext the card paints with."""

    def __init__(self, context: str = "k1", device: str = "d1") -> None:
        self.context, self.device = context, device
        self.titles: list[str] = []
        self.icons: list[tuple[str, str | None]] = []
        self.alerts = 0

    def set_icon(self, ref: str, color: str | None = None) -> None:
        self.icons.append((ref, color))

    def set_title(self, title: str) -> None:
        self.titles.append(title)

    def show_alert(self) -> None:
        self.alerts += 1


class Suspends:
    """A stand-in for suspend(): counts calls, can fail or block."""

    def __init__(self, error: Exception | None = None) -> None:
        self.count = 0
        self.error = error
        self.entered = threading.Event()
        self.gate: threading.Event | None = None

    def __call__(self) -> None:
        self.count += 1
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(_WAIT)
        if self.error is not None:
            raise self.error


@pytest.fixture(name="clock")
def clock_fixture() -> FakeClock:
    return FakeClock()


@pytest.fixture(name="suspends")
def suspends_fixture() -> Suspends:
    return Suspends()


@pytest.fixture(name="sleeper")
def sleeper_fixture(clock: FakeClock, suspends: Suspends) -> Iterator[Sleeper]:
    sleeper = Sleeper(clock=clock, suspender=suspends, interval=3600)
    yield sleeper
    sleeper.stop()


# --- Countdown and fmt_ms ---


def test_countdown_overdue_is_the_time_past_the_deadline(clock: FakeClock) -> None:
    countdown = Countdown(60, clock)

    clock.now += 60
    assert_that(countdown.overdue()).is_equal_to(0)
    clock.now += 500
    assert_that(countdown.overdue()).is_equal_to(500)


@pytest.mark.skipif(sys.platform == "win32", reason="the default clock is time.monotonic on Windows")
def test_the_default_clock_keeps_counting_through_a_system_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    boot = [5000.0]  # stands in for CLOCK_BOOTTIME / CLOCK_MONOTONIC; the real monotonic clock is not moved at all
    monkeypatch.setattr(time, "clock_gettime", lambda _clock_id: boot[0])
    countdown = Countdown(600)
    sleeper = Sleeper(suspender=Suspends(), interval=3600)
    sleeper.start("k1", 600)

    boot[0] += 180  # three minutes in
    boot[0] += 120  # the lid is closed for two minutes
    sleeper.tick()

    assert_that(countdown.remaining()).is_close_to(300, 0.001)
    assert_that(countdown.expired()).is_false()
    assert_that(sleeper.remaining("k1")).is_close_to(300, 0.001)
    assert_that(sleeper.running("k1")).is_true()


def test_countdown_counts_down_on_its_clock_and_expires_at_zero(clock: FakeClock) -> None:
    countdown = Countdown(90, clock)

    assert_that(countdown.remaining()).is_equal_to(90)
    assert_that(countdown.expired()).is_false()
    clock.now += 89.5
    assert_that(countdown.remaining()).is_equal_to(0.5)
    clock.now += 0.5
    assert_that(countdown.expired()).is_true()
    clock.now += 100
    assert_that(countdown.remaining()).is_equal_to(0)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0:00"), (-5, "0:00"), (59, "0:59"), (60, "1:00"), (61.9, "1:01"), (3599, "59:59"), (3600, "1:00:00")]
    + [(86400, "24:00:00"), (3725, "1:02:05")],
)
def test_fmt_ms(seconds: float, text: str) -> None:
    assert_that(fmt_ms(seconds)).is_equal_to(text)


# --- registry: start, cancel, press ---


def test_press_without_a_countdown_suspends(sleeper: Sleeper, suspends: Suspends) -> None:
    assert_that(sleeper.press("k1")).is_equal_to("suspended")
    assert_that(suspends.count).is_equal_to(1)


def test_press_with_a_countdown_cancels_it_and_does_not_suspend(sleeper: Sleeper, suspends: Suspends) -> None:
    sleeper.start("k1", 60)

    assert_that(sleeper.press("k1")).is_equal_to("cancelled")
    assert_that(suspends.count).is_equal_to(0)
    assert_that(sleeper.running("k1")).is_false()


def test_press_only_cancels_its_own_keys_countdown(sleeper: Sleeper, suspends: Suspends) -> None:
    sleeper.start("k2", 60)

    assert_that(sleeper.press("k1")).is_equal_to("suspended")
    assert_that(sleeper.running("k2")).is_true()


def test_after_restarts_a_running_countdown_with_the_new_length(sleeper: Sleeper, clock: FakeClock) -> None:
    sleeper.start("k1", 60)
    clock.now += 30
    sleeper.start("k1", 600)

    assert_that(sleeper.remaining("k1")).is_equal_to(600)


def test_a_failed_suspend_on_press_raises_the_power_error(clock: FakeClock) -> None:
    sleeper = Sleeper(clock=clock, suspender=Suspends(PowerError("no logind")), interval=3600)

    with pytest.raises(PowerError, match="no logind"):
        sleeper.press("k1")
    with pytest.raises(PowerError):  # the failed suspend does not leave the key stuck as pending
        sleeper.press("k1")


# --- expiry ---


def test_expiry_suspends_exactly_once_and_clears(sleeper: Sleeper, clock: FakeClock, suspends: Suspends) -> None:
    sleeper.start("k1", 60)
    clock.now += 59
    sleeper.tick()
    assert_that(suspends.count).is_equal_to(0)

    clock.now += 1
    sleeper.tick()
    sleeper.tick()

    assert_that(suspends.count).is_equal_to(1)
    assert_that(sleeper.running("k1")).is_false()
    assert_that(sleeper.soonest_text()).is_equal_to("")


def test_a_second_tick_during_the_suspend_does_not_suspend_again(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    suspends.gate = threading.Event()
    sleeper.start("k1", 5)
    clock.now += 5
    first = threading.Thread(target=sleeper.tick)
    first.start()
    assert suspends.entered.wait(_WAIT)

    sleeper.tick()  # races the suspend in flight
    assert_that(sleeper.press("k1")).is_equal_to("pending")  # and so does a press at that moment

    suspends.gate.set()
    first.join(_WAIT)
    assert_that(suspends.count).is_equal_to(1)
    assert_that(sleeper.press("k1")).is_equal_to("suspended")  # a later press works again


def test_a_press_at_the_moment_of_expiry_before_the_tick_cancels_instead(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    sleeper.start("k1", 5)
    clock.now += 5

    assert_that(sleeper.press("k1")).is_equal_to("cancelled")
    sleeper.tick()

    assert_that(suspends.count).is_equal_to(0)


def test_the_registry_lock_is_not_held_while_suspending(clock: FakeClock) -> None:
    held: list[bool] = []

    def suspender() -> None:
        held.append(sleeper.lock_held())
        sleeper.start("other", 5)  # would deadlock on a held lock

    sleeper = Sleeper(clock=clock, suspender=suspender, interval=3600)
    sleeper.start("k1", 1)
    clock.now += 1
    sleeper.tick()

    assert_that(held).is_equal_to([False])


def test_a_countdown_found_long_overdue_is_dropped_never_fired_late(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    sleeper.start("k1", 60)
    clock.now += 60 + 30  # the process was stalled well past the deadline

    sleeper.tick()

    assert_that(suspends.count).is_equal_to(0)
    assert_that(sleeper.running("k1")).is_false()


def test_a_failed_suspend_alerts_the_live_key_and_clears_state(clock: FakeClock) -> None:
    suspends = Suspends(PowerError("refused"))
    sleeper = Sleeper(clock=clock, suspender=suspends, interval=3600)
    ctx = FakeCtx()
    sleeper.track(ctx)  # type: ignore[arg-type]
    sleeper.start("k1", 1)
    clock.now += 1

    sleeper.tick()

    assert_that(ctx.alerts).is_equal_to(1)
    assert_that(sleeper.running("k1")).is_false()


def test_a_failed_suspend_of_a_key_that_is_gone_is_only_logged(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    sleeper = Sleeper(clock=clock, suspender=Suspends(PowerError("refused")), interval=3600)
    sleeper.start("k1", 1)
    clock.now += 1

    sleeper.tick()

    assert_that(caplog.text).contains("refused")


# --- system sleep, one suspend per tick ---


def test_a_short_system_sleep_inside_a_countdown_still_fires_on_time(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    sleeper.start("k1", 600)
    clock.now += 180
    clock.now += 120  # the lid is closed for two minutes
    sleeper.tick()

    assert_that(sleeper.remaining("k1")).is_equal_to(300)
    assert_that(suspends.count).is_equal_to(0)
    clock.now += 300
    sleeper.tick()
    assert_that(suspends.count).is_equal_to(1)


def test_a_countdown_whose_machine_slept_through_its_deadline_is_dropped_not_fired(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    sleeper.start("k1", 60)
    clock.now += 8 * 3600 + 60  # suspended overnight

    sleeper.tick()

    assert_that(suspends.count).is_equal_to(0)
    assert_that(sleeper.running("k1")).is_false()


def test_a_countdown_still_running_after_a_system_sleep_is_dropped_at_the_next_tick(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    sleeper.start("a", 60)
    sleeper.start("b", 600)
    clock.now += 60
    sleeper.tick()  # a fires, the machine sleeps
    clock.now += 8 * 3600 + 1  # suspended overnight

    sleeper.tick()

    assert_that(suspends.count).is_equal_to(1)
    assert_that(sleeper.running("b")).is_false()
    clock.now += 600
    sleeper.tick()
    assert_that(suspends.count).is_equal_to(1)


def test_two_countdowns_due_in_one_tick_suspend_once(sleeper: Sleeper, clock: FakeClock, suspends: Suspends) -> None:
    sleeper.start("a", 60)
    sleeper.start("b", 60)
    clock.now += 60

    sleeper.tick()
    sleeper.tick()

    assert_that(suspends.count).is_equal_to(1)
    assert_that(sleeper.running("a") or sleeper.running("b")).is_false()


# --- cancel all ---


def test_cancel_all_stops_every_countdown_and_repaints_the_live_keys_idle(sleeper: Sleeper, suspends: Suspends) -> None:
    ctx = FakeCtx("a")
    sleeper.track(ctx)  # type: ignore[arg-type]
    sleeper.start("a", 60)
    sleeper.start("gone", 600)

    assert_that(sleeper.cancel_all()).is_equal_to(2)

    assert_that(sleeper.soonest_text()).is_equal_to("")
    assert_that(ctx.titles[-1]).is_equal_to("")
    assert_that(ctx.icons[-1]).is_equal_to(("fas:moon", "#ffffff"))
    assert_that(suspends.count).is_equal_to(0)


def test_cancel_all_without_countdowns_returns_zero(sleeper: Sleeper) -> None:
    assert_that(sleeper.cancel_all()).is_equal_to(0)


# --- painting and page switches ---


def test_idle_key_shows_the_moon_without_a_title(sleeper: Sleeper) -> None:
    ctx = FakeCtx()

    sleeper.track(ctx)  # type: ignore[arg-type]

    assert_that(ctx.icons).is_equal_to([("fas:moon", "#ffffff")])
    assert_that(ctx.titles).is_equal_to([""])


def test_a_tick_repaints_live_keys_with_the_remaining_time(sleeper: Sleeper, clock: FakeClock) -> None:
    ctx = FakeCtx()
    sleeper.track(ctx)  # type: ignore[arg-type]
    sleeper.start("k1", 90)

    clock.now += 0.4
    sleeper.tick()

    assert_that(ctx.titles[-1]).is_equal_to("1:30")
    assert_that(ctx.icons[-1][1]).is_not_equal_to("#ffffff")
    clock.now += 30
    sleeper.tick()
    assert_that(ctx.titles[-1]).is_equal_to("1:00")


def test_a_tick_does_not_repaint_idle_keys(sleeper: Sleeper) -> None:
    idle, running = FakeCtx("idle"), FakeCtx("k1")
    sleeper.track(idle)  # type: ignore[arg-type]
    sleeper.track(running)  # type: ignore[arg-type]
    sleeper.start("k1", 90)
    painted = (len(idle.titles), len(running.titles))

    sleeper.tick()

    assert_that(len(idle.titles)).is_equal_to(painted[0])
    assert_that(len(running.titles)).is_equal_to(painted[1] + 1)


def test_a_countdown_survives_the_key_disappearing_and_the_return_shows_the_remaining_time(
    sleeper: Sleeper, clock: FakeClock, suspends: Suspends
) -> None:
    first = FakeCtx()
    sleeper.track(first)  # type: ignore[arg-type]
    sleeper.start("k1", 120)
    sleeper.untrack(first)  # type: ignore[arg-type]

    clock.now += 60
    sleeper.tick()
    assert_that(sleeper.running("k1")).is_true()
    assert_that(first.titles[-1]).is_equal_to("2:00")  # nothing painted while away

    again = FakeCtx()
    sleeper.track(again)  # type: ignore[arg-type]
    assert_that(again.titles).is_equal_to(["1:00"])

    clock.now += 60
    sleeper.tick()
    assert_that(suspends.count).is_equal_to(1)


def test_an_expiring_countdown_leaves_an_idle_key(sleeper: Sleeper, clock: FakeClock) -> None:
    ctx = FakeCtx()
    sleeper.track(ctx)  # type: ignore[arg-type]
    sleeper.start("k1", 2)
    clock.now += 2

    sleeper.tick()

    assert_that(ctx.titles[-1]).is_equal_to("")
    assert_that(ctx.icons[-1]).is_equal_to(("fas:moon", "#ffffff"))


def test_concurrent_paints_of_one_key_leave_the_newest_remaining_time(sleeper: Sleeper, clock: FakeClock) -> None:
    gate, in_first = threading.Event(), threading.Event()

    class Slow(FakeCtx):
        def set_title(self, title: str) -> None:
            if not in_first.is_set():
                in_first.set()
                assert gate.wait(_WAIT)
            super().set_title(title)

    ctx = Slow()
    sleeper.start("k1", 60)
    face = sleeper.track(ctx, paint=False)  # type: ignore[arg-type]
    first = threading.Thread(target=sleeper.paint, args=(face,))
    first.start()
    assert in_first.wait(_WAIT)
    clock.now += 10
    second = threading.Thread(target=sleeper.paint, args=(face,))
    second.start()

    gate.set()
    first.join(_WAIT)
    second.join(_WAIT)

    assert_that(ctx.titles[-1]).is_equal_to("0:50")


def test_soonest_text_is_the_soonest_running_countdown(sleeper: Sleeper, clock: FakeClock) -> None:
    assert_that(sleeper.soonest_text()).is_equal_to("")
    sleeper.start("k1", 600)
    sleeper.start("k2", 90)
    clock.now += 0.5

    assert_that(sleeper.soonest_text()).is_equal_to("1:30")


# --- the ticker thread ---


def test_the_ticker_expires_countdowns_on_its_own(clock: FakeClock, suspends: Suspends) -> None:
    sleeper = Sleeper(clock=clock, suspender=suspends, interval=0.01)
    sleeper.start("k1", 5)
    clock.now += 5
    sleeper.start_ticker()
    try:
        assert_that(suspends.entered.wait(_WAIT)).is_true()
    finally:
        sleeper.stop()

    assert_that(suspends.count).is_equal_to(1)
    assert_that(sleeper.ticker_alive()).is_false()


def test_start_is_idempotent_and_stop_ends_the_thread_and_may_be_repeated(sleeper: Sleeper) -> None:
    sleeper.start_ticker()
    sleeper.start_ticker()
    assert_that([t for t in threading.enumerate() if t.name == "sleep-ticker"]).is_length(1)

    sleeper.stop()
    sleeper.stop()

    assert_that([t for t in threading.enumerate() if t.name == "sleep-ticker" and t.is_alive()]).is_empty()
    sleeper.start_ticker()
    assert_that(sleeper.ticker_alive()).is_true()


def test_stop_from_the_ticker_thread_does_not_join_itself(clock: FakeClock) -> None:
    errors: list[BaseException] = []
    done = threading.Event()
    holder: list[Sleeper] = []

    def suspender() -> None:
        try:
            holder[0].stop()
        except BaseException as exc:  # noqa: BLE001 - the test reports any failure
            errors.append(exc)
        done.set()

    sleeper = Sleeper(clock=clock, suspender=suspender, interval=0.01)
    holder.append(sleeper)
    sleeper.start("k1", 1)
    clock.now += 1
    sleeper.start_ticker()

    assert_that(done.wait(_WAIT)).is_true()
    assert_that(errors).is_empty()
    sleeper.stop()


def test_a_stop_during_start_waits_for_the_thread_to_be_running(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_thread = threading.Thread
    published, stopping, errors = threading.Event(), threading.Event(), []

    class SlowStart(real_thread):  # type: ignore[misc, valid-type]
        def start(self) -> None:
            if self.name == "sleep-ticker":
                published.set()
                stopping.wait(_WAIT)  # a window in which stop() could see the thread before it was started
            super().start()

    sleeper = Sleeper(clock=clock, suspender=Suspends(), interval=0.05)

    def stopper() -> None:
        assert published.wait(_WAIT)
        stopping.set()
        try:
            sleeper.stop()
        except RuntimeError as exc:
            errors.append(exc)

    stop_thread = real_thread(target=stopper)
    stop_thread.start()
    monkeypatch.setattr(threading, "Thread", SlowStart)
    sleeper.start_ticker()
    monkeypatch.undo()
    stop_thread.join(_WAIT)

    assert_that(errors).is_empty()
    assert_that(sleeper.ticker_alive()).is_false()


# --- through the SDK loop ---


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    return load_plugin()


@pytest.fixture(name="loop_clock")
def loop_clock_fixture(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[FakeClock]:
    sleeper = Sleeper(clock=clock, suspender=lambda: power.suspend(), interval=3600)
    monkeypatch.setattr(sleep_card, "_sleeper", sleeper)
    yield clock
    sleeper.stop()


@pytest.fixture(name="suspended")
def suspended_fixture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(power, "suspend", lambda: calls.append("suspend"))
    monkeypatch.setattr(power, "lock", lambda: calls.append("lock"))
    return calls


@pytest.fixture(name="key")
def key_fixture(plugin: ModuleType, loop_clock: FakeClock, suspended: list[str]) -> Iterator[Harness]:
    harness = Harness(plugin, _CARD, "SleepCard")
    yield harness
    harness.close()


def _face(key: Harness) -> tuple[dict, str]:
    icon = key.recv_until("set_image")["payload"]
    return icon, key.recv_until("set_title")["payload"]["title"]


def _run(key: Harness, action_id: str, **args: Any) -> dict:
    return key.run_action(action_id, args)


def _title_now(key: Harness) -> str:
    """Wait for the next paint and return its title (paints follow every state change)."""
    return _face(key)[1]


def _variable(key: Harness, name: str = "sleep_in") -> dict:
    key.send_event("get_variable", {"request": f"v-{name}", "name": name})
    return key.recv_until("variable_value")["payload"]


def test_the_key_starts_idle(key: Harness) -> None:
    key.appear({})

    icon, title = _face(key)

    assert_that(icon).is_equal_to({"icon": "fas:moon", "color": "#ffffff"})
    assert_that(title).is_equal_to("")


def test_press_with_no_countdown_suspends(key: Harness, suspended: list[str]) -> None:
    key.appear({})
    _face(key)

    result = _run(key, _PRESS)

    assert_that(result).contains_entry({"ok": True})
    assert_that(suspended).is_equal_to(["suspend"])


def test_a_failing_suspend_is_an_action_error(key: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise PowerError("suspend refused by logind")

    monkeypatch.setattr(power, "suspend", boom)
    key.appear({})
    _face(key)

    result = _run(key, _PRESS)

    assert_that(result).contains_entry({"ok": False})
    assert_that(result["error"]).contains("suspend refused by logind")


def test_after_then_press_cancels_without_suspending(key: Harness, suspended: list[str]) -> None:
    key.appear({})
    _face(key)

    assert_that(_run(key, _AFTER, minutes=1)).contains_entry({"ok": True})
    assert_that(_title_now(key)).is_equal_to("1:00")
    assert_that(_run(key, _PRESS)).contains_entry({"ok": True})

    assert_that(_title_now(key)).is_equal_to("")
    assert_that(suspended).is_empty()
    assert_that([m["event"] for m in key.sent]).contains("show_ok")


def test_long_during_a_one_minute_countdown_restarts_at_ten(key: Harness) -> None:
    key.appear({})
    _face(key)
    _run(key, _AFTER, minutes=1)
    assert_that(_title_now(key)).is_equal_to("1:00")

    _run(key, _AFTER, minutes=10)

    assert_that(_title_now(key)).is_equal_to("10:00")


def test_expiry_through_the_loop_suspends_once_and_goes_idle(
    key: Harness, loop_clock: FakeClock, suspended: list[str]
) -> None:
    key.appear({})
    _face(key)
    _run(key, _AFTER, minutes=1)
    _title_now(key)

    loop_clock.now += 60
    sleep_card._sleeper.tick()

    assert_that(_title_now(key)).is_equal_to("")
    assert_that(suspended).is_equal_to(["suspend"])


def test_page_switch_away_and_back_keeps_counting_and_shows_the_remaining_time(
    key: Harness, loop_clock: FakeClock, suspended: list[str]
) -> None:
    key.appear({})
    _face(key)
    _run(key, _AFTER, minutes=2)
    _title_now(key)

    key.send_event("will_disappear", {}, CONTEXT)
    assert_that(wait_for(lambda: not sleep_card._sleeper.tracked(CONTEXT))).is_true()
    loop_clock.now += 30
    sleep_card._sleeper.tick()
    key.appear({})

    assert_that(_title_now(key)).is_equal_to("1:30")
    loop_clock.now += 90
    sleep_card._sleeper.tick()
    assert_that(_title_now(key)).is_equal_to("")
    assert_that(suspended).is_equal_to(["suspend"])


def test_sleep_in_is_empty_then_the_soonest_countdown(key: Harness, loop_clock: FakeClock) -> None:
    key.appear({})
    _face(key)
    assert_that(_variable(key)).contains_entry({"ok": True}, {"value": ""})

    _run(key, _AFTER, minutes=5)
    _title_now(key)

    assert_that(_variable(key)).contains_entry({"value": "5:00"})


def test_starting_and_cancelling_signal_the_variable(key: Harness) -> None:
    key.appear({})
    _face(key)

    _run(key, _AFTER, minutes=1)

    assert_that(key.recv_until("variable_updated")["payload"]["name"]).is_equal_to("sleep_in")


@pytest.mark.parametrize("minutes", [0, 1441, True, "5", 2.5, None])
def test_bad_minutes_are_errors_and_start_nothing(key: Harness, minutes: Any) -> None:
    key.appear({})
    _face(key)

    result = _run(key, _AFTER, minutes=minutes)

    assert_that(result).contains_entry({"ok": False})
    assert_that(sleep_card._sleeper.running(CONTEXT)).is_false()


def test_minutes_default_to_one(key: Harness) -> None:
    key.appear({})
    _face(key)

    _run(key, _AFTER)

    assert_that(_title_now(key)).is_equal_to("1:00")


def test_the_cancel_action_cancels_every_countdown_and_reports_how_many(key: Harness, suspended: list[str]) -> None:
    key.appear({})
    _face(key)
    _run(key, _AFTER, minutes=5)
    _title_now(key)
    sleep_card._sleeper.start("other", 60)

    result = key.run_action("com.decker.utilities.sleep-cancel", {}, with_card=False)

    assert_that(result).contains_entry({"ok": True}, {"value": 2})
    assert_that(_title_now(key)).is_equal_to("")
    assert_that(_variable(key)).contains_entry({"value": ""})
    assert_that(suspended).is_empty()


def test_the_cancel_action_with_nothing_running_returns_zero(key: Harness) -> None:
    result = key.run_action("com.decker.utilities.sleep-cancel", {}, with_card=False)

    assert_that(result).contains_entry({"ok": True}, {"value": 0})


def test_the_sleep_and_lock_actions_call_power(key: Harness, suspended: list[str]) -> None:
    assert_that(key.run_action("com.decker.utilities.sleep", {}, with_card=False)).contains_entry({"ok": True})
    assert_that(key.run_action("com.decker.utilities.lock", {}, with_card=False)).contains_entry({"ok": True})

    assert_that(suspended).is_equal_to(["suspend", "lock"])


def test_a_failing_lock_is_an_action_error(key: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise PowerError("lock refused")

    monkeypatch.setattr(power, "lock", boom)

    result = key.run_action("com.decker.utilities.lock", {}, with_card=False)

    assert_that(result).contains_entry({"ok": False})
    assert_that(result["error"]).contains("lock refused")


def test_the_first_key_and_a_countdown_start_one_ticker(plugin: ModuleType, loop_clock: FakeClock) -> None:
    key = Harness(plugin, _CARD, "SleepCard")
    try:
        assert_that(sleep_card._sleeper.ticker_alive()).is_false()
        key.appear({})
        assert_that(wait_for(sleep_card._sleeper.ticker_alive)).is_true()
        _face(key)
        _run(key, _AFTER, minutes=1)
    finally:
        key.close()

    assert_that([t for t in threading.enumerate() if t.name == "sleep-ticker"]).is_length(1)


def wait_for(done: Callable[[], bool]) -> bool:
    """Poll a condition for a bounded time."""
    stop = threading.Event()
    for _ in range(_WAIT * 100):
        if done():
            return True
        stop.wait(0.01)
    return done()


# --- manifest ---


def test_the_manifest_declares_the_card_actions_and_variable() -> None:
    cards = {c.id: c for c in _MANIFEST.cards}
    actions = {a.id: a for a in _MANIFEST.actions}
    card = cards[_CARD]

    assert_that(card.icon).is_equal_to("fas:moon")
    assert_that(card.bindings["press"].action).is_equal_to(_PRESS)
    assert_that(card.bindings["double_press"].action).is_equal_to(_AFTER)
    assert_that(card.bindings["double_press"].args).is_equal_to({"minutes": 1})
    assert_that(card.bindings["long_press"].args).is_equal_to({"minutes": 10})
    assert_that(actions["com.decker.utilities.sleep"].icon).is_equal_to("fas:moon")
    assert_that(actions["com.decker.utilities.sleep"].scope).is_equal_to("global")
    assert_that(actions["com.decker.utilities.lock"].icon).is_equal_to("fas:lock")
    assert_that(actions[_PRESS].scope).is_equal_to("plugin")
    assert_that(actions[_AFTER].scope).is_equal_to("plugin")
    minutes = actions[_AFTER].settings[0]
    assert_that((minutes.key, minutes.default)).is_equal_to(("minutes", 1))
    assert_that([v.name for v in _MANIFEST.variables]).contains("sleep_in")
    cancel = actions["com.decker.utilities.sleep-cancel"]
    assert_that((cancel.name, cancel.icon, cancel.scope)).is_equal_to(("Cancel sleep countdowns", "fas:ban", "global"))
    assert_that(cancel.tooltip).contains("removed").contains("keep running")
