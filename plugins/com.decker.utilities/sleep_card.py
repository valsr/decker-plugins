"""Sleep and Lock: the global actions, the Sleep card with its countdowns, and the ``sleep_in`` variable.

Countdowns live in one registry keyed by the card's context id, not on the card, so they keep running while the key's
page is switched away; ``will_appear`` repaints the key with what is left. One ticker thread (a daemon, started by the
first Sleep key or countdown) ticks the registry once a second: it repaints the live keys, signals ``sleep_in`` and, at
zero, suspends. A countdown is removed from the registry (under its lock) before it fires and the suspend itself runs
outside that lock, so a racing tick or press can never fire it twice. Countdowns are never fired late and are lost with
the plugin process.

The ticker is not an SDK ``@main``: the SDK runs mains one after another, and the brightness main never returns.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import power
from decker_plugin_sdk import (
    ActionCallContext,
    ActionError,
    CardContext,
    DeckerPlugin,
    action,
    card,
    signal_variable_updated,
    variable,
)
from power import PowerError
from ticker import Ticker
from timers import Countdown, fmt_ms

_log = logging.getLogger(__name__)

CARD = "com.decker.utilities.sleep"
_ICON = "fas:moon"
_IDLE_TINT = "#ffffff"
_RUNNING_TINT = "#f5b041"
_VARIABLE = "sleep_in"
_MIN_MINUTES, _MAX_MINUTES = 1, 1440
_LATE_SECONDS = 5.0  # a countdown found this far past its deadline is dropped instead of fired

Outcome = Literal["cancelled", "pending", "suspended"]


@dataclass
class _Face:
    """A live Sleep key; the lock serialises its paints so the last one shows the newest time."""

    ctx: CardContext
    lock: threading.Lock = field(default_factory=threading.Lock)


class Sleeper:
    """The countdown registry, the live keys and the 1 Hz ticker thread."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        suspender: Callable[[], None] | None = None,
        interval: float = 1.0,
        wall_clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock or _sleep_inclusive_clock()
        self._suspender = suspender or (lambda: power.suspend())
        self._lock = threading.Lock()
        self._countdowns: dict[str, Countdown] = {}
        self._firing: set[str] = set()
        self._faces: dict[str, _Face] = {}
        self._ticker = Ticker(interval, self.tick, "sleep-ticker")

    # --- registry

    def start(self, context: str, seconds: float) -> None:
        """Start (or restart) the key's countdown."""
        with self._lock:
            self._countdowns[context] = Countdown(seconds, self._clock, self._wall_clock)
        self._changed(context)

    def running(self, context: str) -> bool:
        with self._lock:
            return context in self._countdowns

    def remaining(self, context: str) -> float | None:
        with self._lock:
            countdown = self._countdowns.get(context)
            return None if countdown is None else countdown.remaining()

    def lock_held(self) -> bool:
        return self._lock.locked()

    def soonest_text(self) -> str:
        """The soonest running countdown as ``fmt_ms``, empty when none runs."""
        with self._lock:
            left = [c.remaining() for c in self._countdowns.values()]
        return fmt_ms(math.ceil(min(left))) if left else ""

    def cancel_all(self) -> int:
        """Cancel every running countdown (including those of keys that no longer exist); returns how many."""
        with self._lock:
            count = len(self._countdowns)
            self._countdowns.clear()
            faces = list(self._faces.values())
        for face in faces:
            self.paint(face)
        _signal()
        return count

    def clear(self) -> None:
        with self._lock:
            self._countdowns.clear()
            self._faces.clear()
            self._firing.clear()

    def press(self, context: str) -> Outcome:
        """Cancel the key's countdown, else suspend; raises PowerError when the suspend fails."""
        with self._lock:
            if self._countdowns.pop(context, None) is not None:
                outcome: Outcome = "cancelled"
            elif context in self._firing:
                return "pending"  # a suspend is already on its way
            else:
                outcome = "suspended"
                self._firing.add(context)
        if outcome == "cancelled":
            self._changed(context)
            return outcome
        try:
            self._suspender()
        finally:
            with self._lock:
                self._firing.discard(context)
        return outcome

    # --- keys

    def track(self, ctx: CardContext, paint: bool = True) -> _Face:
        face = _Face(ctx)
        with self._lock:
            self._faces[ctx.context] = face
        if paint:
            self.paint(face)
        return face

    def tracked(self, context: str) -> bool:
        with self._lock:
            return context in self._faces

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._faces.pop(ctx.context, None)

    def paint(self, face: _Face) -> None:
        """Draw the remaining time (or the idle moon); the time is read inside the key's lock so the newest wins."""
        with face.lock:
            left = self.remaining(face.ctx.context)
            face.ctx.set_icon(_ICON, _IDLE_TINT if left is None else _RUNNING_TINT)
            face.ctx.set_title("" if left is None else fmt_ms(math.ceil(left)))

    def _changed(self, context: str) -> None:
        with self._lock:
            face = self._faces.get(context)
        if face is not None:
            self.paint(face)
        _signal()

    # --- ticking

    def tick(self) -> None:
        """Expire what is due, repaint the live keys, signal ``sleep_in``; safe to call from any thread."""
        with self._lock:
            had_any = bool(self._countdowns)
            due: list[str] = []
            for context, countdown in list(self._countdowns.items()):
                overdue = countdown.overdue()
                if not countdown.expired() and overdue <= _LATE_SECONDS:
                    continue
                del self._countdowns[context]
                if overdue > _LATE_SECONDS:  # the machine slept or the process stalled: never suspend late
                    _log.warning("sleep countdown of %s is %.0f s overdue; dropped", context, overdue)
                else:
                    due.append(context)
            fire = due[:1]  # one suspend per tick: a second would suspend again right after the wake
            for context in due[1:]:
                _log.info("sleep countdown of %s fell due with another; dropped", context)
            self._firing.update(fire)
            faces = list(self._faces.values())
        for face in faces:
            self.paint(face)
        if had_any:
            _signal()
        for context in fire:
            self._fire(context)

    def _fire(self, context: str) -> None:
        try:
            self._suspender()
        except Exception as exc:
            _log.warning("sleep countdown of %s could not suspend: %s", context, exc)
            with self._lock:
                face = self._faces.get(context)
            if face is not None:
                face.ctx.show_alert()
        finally:
            with self._lock:
                self._firing.discard(context)

    def start_ticker(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def ticker_alive(self) -> bool:
        return self._ticker.alive()


def _sleep_inclusive_clock() -> Callable[[], float]:
    """A clock that keeps counting while the machine is suspended (CLOCK_BOOTTIME on Linux, wall time elsewhere)."""
    if hasattr(time, "CLOCK_BOOTTIME"):
        return lambda: time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.time


def _signal() -> None:
    try:
        signal_variable_updated(_VARIABLE)
    except RuntimeError:  # no plugin runtime is running
        _log.debug("sleep_in not signalled: no runtime")


_sleeper = Sleeper()


def reset_for_tests() -> None:
    """Stop the ticker and forget every countdown and key."""
    _sleeper.stop()
    _sleeper.clear()


@card(CARD)
class SleepCard(DeckerPlugin):
    """A moon that shows the time left of this key's sleep countdown."""

    def on_will_appear(self, ctx: CardContext) -> None:
        _sleeper.start_ticker()
        _sleeper.track(ctx)

    def on_will_disappear(self, ctx: CardContext) -> None:
        _sleeper.untrack(ctx)  # the countdown itself keeps running


def _key_of(ctx: ActionCallContext) -> Any:
    if ctx.card is None:
        raise ActionError("Sleep actions need a Sleep card")
    return ctx.card


def _minutes(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not _MIN_MINUTES <= raw <= _MAX_MINUTES:
        raise ActionError(f"minutes must be a whole number from {_MIN_MINUTES} to {_MAX_MINUTES}, not {raw!r}")
    return raw


@action("com.decker.utilities.sleep")
def sleep(ctx: ActionCallContext) -> None:  # pylint: disable=unused-argument
    """Put the computer to sleep now."""
    try:
        power.suspend()
    except PowerError as exc:
        raise ActionError(str(exc)) from exc


@action("com.decker.utilities.lock")
def lock(ctx: ActionCallContext) -> None:  # pylint: disable=unused-argument
    """Lock the screen."""
    try:
        power.lock()
    except PowerError as exc:
        raise ActionError(str(exc)) from exc


@action("com.decker.utilities.sleep-press")
def sleep_press(ctx: ActionCallContext) -> None:
    """Cancel this key's countdown, or put the computer to sleep when none is running."""
    key = _key_of(ctx)
    try:
        outcome = _sleeper.press(key.context)
    except PowerError as exc:
        raise ActionError(str(exc)) from exc
    if outcome == "cancelled":
        key.show_ok()


@action("com.decker.utilities.sleep-after")
def sleep_after(ctx: ActionCallContext) -> None:
    """Start (or restart) this key's countdown to sleep."""
    key = _key_of(ctx)
    _sleeper.start(key.context, _minutes(ctx.args.get("minutes", 1)) * 60)
    _sleeper.start_ticker()


@action("com.decker.utilities.sleep-cancel")
def sleep_cancel(ctx: ActionCallContext) -> int:  # pylint: disable=unused-argument
    """Cancel every running Sleep countdown, also those of removed keys; returns how many were running."""
    return _sleeper.cancel_all()


@variable(_VARIABLE)
def _sleep_in() -> str:
    return _sleeper.soonest_text()
