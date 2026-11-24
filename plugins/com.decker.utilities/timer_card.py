"""The Timer card: a pausable countdown drawn as a ring or a bar, with the time left.

Timers live in one registry keyed by the card's context id, so they keep running while the key's page is switched
away; ``will_appear`` repaints the key with what is left. One daemon ticker thread (started by the first press, at 4 Hz)
repaints the running keys only; idle, paused and finished keys are painted when their state changes. A timer is never
rung late (see ``timers.Timer``) and is lost with the plugin process. When one finishes the key shows ``0:00`` and
flashes an alert three times, half a second apart, from a short-lived thread that a press, a reset or a duration
change cancels.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardContext, DeckerPlugin, action, card
from drawing import draw_progress, draw_time, progress_color
from ticker import Ticker
from timers import Timer, TimerState, fmt_ms

_log = logging.getLogger(__name__)

CARD = "com.decker.utilities.timer"
_INTERVAL = 0.25
_ALERT_DELAY = 0.5
_ALERTS = 3
_DEFAULT_MINUTES, _MAX_MINUTES = 5, 1440
_MAX_SECONDS = 59
_DEFAULT_WIDTH = 6
_DEFAULT_COLOR, _DEFAULT_COLOR_2 = "#2ecc71", "#e74c3c"


@dataclass
class _Face:
    """A live Timer key; the lock serialises its paints so the last one shows the newest state."""

    ctx: CardContext
    lock: threading.Lock = field(default_factory=threading.Lock)


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def duration_of(settings: dict[str, Any]) -> int:
    """Seconds from the ``minutes`` and ``seconds`` settings (defaults 5 and 0 when missing or malformed)."""
    minutes = _int(settings.get("minutes"), _DEFAULT_MINUTES, 0, _MAX_MINUTES)
    return minutes * 60 + _int(settings.get("seconds"), 0, 0, _MAX_SECONDS)


class Timers:
    """The timer registry, the live keys, the finish alerts and the 4 Hz ticker."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        interval: float = _INTERVAL,
        alert_delay: float = _ALERT_DELAY,
    ) -> None:
        self._clock = clock
        self._alert_delay = alert_delay
        self._lock = threading.Lock()
        self._timers: dict[str, Timer] = {}
        self._faces: dict[str, _Face] = {}
        self._alerts: dict[str, threading.Event] = {}  # the cancel switch of each key's running alert burst
        self._alerting = 0  # alert threads still alive
        self._ticker = Ticker(interval, self.tick, "timer-ticker")

    # --- registry

    def state(self, context: str) -> TimerState:
        with self._lock:
            timer = self._timers.get(context)
            return "idle" if timer is None else timer.state

    def remaining(self, context: str) -> float:
        with self._lock:
            timer = self._timers.get(context)
            return 0.0 if timer is None else timer.remaining()

    def tracked(self, context: str) -> bool:
        with self._lock:
            return context in self._faces

    def pending_alerts(self) -> int:
        """How many alert bursts are still running."""
        with self._lock:
            return self._alerting

    def clear(self) -> None:
        with self._lock:
            for cancel in self._alerts.values():
                cancel.set()
            self._timers.clear()
            self._faces.clear()
            self._alerts.clear()

    def _timer_for(self, context: str, duration: int) -> Timer:
        """The key's timer; a different duration replaces it with a fresh idle one. Call with the lock held."""
        timer = self._timers.get(context)
        if timer is None or timer.duration != duration:
            self._cancel_alert(context)
            timer = self._timers[context] = Timer(duration, self._clock)
        return timer

    def toggle(self, context: str, duration: int) -> TimerState:
        """Start, pause or resume the key's timer (restart a finished one); returns the new state."""
        with self._lock:
            timer = self._timer_for(context, duration)
            self._cancel_alert(context)
            timer.toggle()
            state = timer.state
        self._paint_key(context)
        if state == "running":
            self.start_ticker()
        return state

    def reset(self, context: str) -> None:
        with self._lock:
            timer = self._timers.get(context)
            if timer is not None:
                timer.reset()
            self._cancel_alert(context)
        self._paint_key(context)

    # --- keys

    def track(self, ctx: CardContext, paint: bool = True) -> _Face:
        """A key appeared or its settings changed: keep its timer unless the duration differs, then repaint."""
        with self._lock:
            self._timer_for(ctx.context, duration_of(ctx.settings))
            face = self._faces.get(ctx.context)
            if face is None:
                face = self._faces[ctx.context] = _Face(ctx)
            face.ctx = ctx
        if paint:
            self.paint(face)
        return face

    def settings_changed(self, ctx: CardContext) -> None:
        """A new duration resets the timer to idle with it; any other setting only repaints."""
        self.track(ctx)

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._faces.pop(ctx.context, None)

    def paint(self, face: _Face) -> None:
        """Draw the key; the state is read inside the key's lock so the newest paint shows the newest state."""
        with face.lock:
            settings = face.ctx.settings
            with self._lock:
                timer = self._timers.get(face.ctx.context)
                if timer is None:
                    left = float(duration_of(settings))
                    fraction = 1.0 if left else 0.0
                else:
                    left, fraction = timer.remaining(), timer.fraction_left()
            with face.ctx.canvas.paint() as img:
                img.paste((0, 0, 0, 0), (0, 0, *img.size))
                _draw(img, settings, left, fraction)

    def _paint_key(self, context: str) -> None:
        with self._lock:
            face = self._faces.get(context)
        if face is not None:
            self.paint(face)

    # --- ticking

    def tick(self) -> None:
        """Finish what ran out and repaint the running keys; safe to call from any thread."""
        with self._lock:
            running = [c for c, t in self._timers.items() if t.state == "running"]
            for context in running:
                if self._timers[context].tick():
                    self._start_alert(context)
            faces = [self._faces[c] for c in running if c in self._faces]
        for face in faces:
            self.paint(face)

    def start_ticker(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def ticker_alive(self) -> bool:
        return self._ticker.alive()

    # --- finish alerts (off the ticker and the message loop)

    def _start_alert(self, context: str) -> None:
        """Call with the lock held."""
        self._cancel_alert(context)
        cancel = self._alerts[context] = threading.Event()
        self._alerting += 1
        threading.Thread(target=self._alert, args=(context, cancel), name="timer-alert", daemon=True).start()

    def _cancel_alert(self, context: str) -> None:
        """Call with the lock held."""
        cancel = self._alerts.pop(context, None)
        if cancel is not None:
            cancel.set()

    def _alert(self, context: str, cancel: threading.Event) -> None:
        try:
            for number in range(_ALERTS):
                if (number and cancel.wait(self._alert_delay)) or cancel.is_set():
                    return
                with self._lock:
                    face = self._faces.get(context)
                if face is not None:
                    face.ctx.show_alert()
        except Exception:
            _log.exception("timer alert failed")
        finally:
            with self._lock:
                self._alerting -= 1
                if self._alerts.get(context) is cancel:
                    del self._alerts[context]


def _draw(img: Any, settings: dict[str, Any], left: float, fraction: float) -> None:
    if settings.get("show_progress", True):
        color = progress_color(
            settings.get("color_mode", "solid"),
            settings.get("color", _DEFAULT_COLOR),
            settings.get("color_2", _DEFAULT_COLOR_2),
            fraction,
        )
        width = _int(settings.get("line_width"), _DEFAULT_WIDTH, 1, 20)
        draw_progress(img, settings.get("progress_type", "circle"), fraction, color, width)
    if settings.get("show_time", True):
        draw_time(img, fmt_ms(math.ceil(left)))


_timers = Timers()


def reset_for_tests() -> None:
    """Stop the ticker and forget every timer and key."""
    _timers.stop()
    _timers.clear()


@card(CARD)
class TimerCard(DeckerPlugin):
    """A timer key: press to start, pause or resume; double or long press to reset."""

    def on_will_appear(self, ctx: CardContext) -> None:
        _timers.track(ctx)

    def on_will_disappear(self, ctx: CardContext) -> None:
        _timers.untrack(ctx)  # the timer itself keeps running

    def on_settings_changed(self, ctx: CardContext) -> None:
        _timers.settings_changed(ctx)


def _key_of(ctx: ActionCallContext) -> Any:
    if ctx.card is None:
        raise ActionError("Timer actions need a Timer card")
    return ctx.card


@action("com.decker.utilities.timer-toggle")
def timer_toggle(ctx: ActionCallContext) -> None:
    """Start the Timer, pause it while it runs, resume it while paused, restart it when finished."""
    key = _key_of(ctx)
    duration = duration_of(key.settings)
    if duration <= 0:
        key.show_alert()
        raise ActionError("set a duration")
    _timers.toggle(key.context, duration)


@action("com.decker.utilities.timer-reset")
def timer_reset(ctx: ActionCallContext) -> None:
    """Stop the Timer and show its full duration again."""
    _timers.reset(_key_of(ctx).context)
