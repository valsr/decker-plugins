"""The Stopwatch card: counts up with a press, shown as ``m:ss`` (``h:mm:ss`` from one hour).

Stopwatches live in one registry keyed by the card's context id, so they keep running while the key's page is switched
away; ``will_appear`` repaints the key with the time so far. One daemon ticker thread (started by the first press, at
1 Hz) repaints the running keys only; a stopped key is painted when its state changes. They are lost with the plugin
process.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from decker_plugin_sdk import ActionCallContext, ActionError, CardContext, DeckerPlugin, action, card
from drawing import draw_time
from ticker import Ticker
from timers import Stopwatch, fmt_ms, sleep_inclusive_clock

CARD = "com.decker.utilities.stopwatch"
_INTERVAL = 1.0


@dataclass
class _Face:
    """A live Stopwatch key; the lock serialises its paints so the last one shows the newest time."""

    ctx: CardContext
    lock: threading.Lock = field(default_factory=threading.Lock)


class Stopwatches:
    """The stopwatch registry, the live keys and the 1 Hz ticker."""

    def __init__(self, clock: Callable[[], float] = sleep_inclusive_clock, interval: float = _INTERVAL) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._watches: dict[str, Stopwatch] = {}
        self._faces: dict[str, _Face] = {}
        self._ticker = Ticker(interval, self.tick, "stopwatch-ticker")

    # --- registry

    def running(self, context: str) -> bool:
        with self._lock:
            watch = self._watches.get(context)
            return watch is not None and watch.running

    def elapsed(self, context: str) -> float:
        with self._lock:
            watch = self._watches.get(context)
            return 0.0 if watch is None else watch.elapsed()

    def tracked(self, context: str) -> bool:
        with self._lock:
            return context in self._faces

    def clear(self) -> None:
        with self._lock:
            self._watches.clear()
            self._faces.clear()

    def _watch_for(self, context: str) -> Stopwatch:
        """The key's stopwatch, created stopped on first use. Call with the lock held."""
        watch = self._watches.get(context)
        if watch is None:
            watch = self._watches[context] = Stopwatch(self._clock)
        return watch

    def toggle(self, context: str) -> bool:
        """Start or pause the key's stopwatch; returns whether it runs now."""
        with self._lock:
            watch = self._watch_for(context)
            watch.toggle()
            running = watch.running
        self._paint_key(context)
        if running:
            self.start_ticker()
        return running

    def reset(self, context: str) -> None:
        with self._lock:
            watch = self._watches.get(context)
            if watch is not None:
                watch.reset()
        self._paint_key(context)

    # --- keys

    def track(self, ctx: CardContext, paint: bool = True) -> _Face:
        """A key appeared: keep its stopwatch and repaint."""
        with self._lock:
            self._watch_for(ctx.context)
            face = self._faces.get(ctx.context)
            if face is None:
                face = self._faces[ctx.context] = _Face(ctx)
            face.ctx = ctx
        if paint:
            self.paint(face)
        return face

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._faces.pop(ctx.context, None)

    def paint(self, face: _Face) -> None:
        """Draw the key; the time is read inside the key's lock so the newest paint shows the newest time."""
        with face.lock:
            with self._lock:
                watch = self._watches.get(face.ctx.context)
                elapsed = 0.0 if watch is None else watch.elapsed()
            with face.ctx.canvas.paint() as img:
                img.paste((0, 0, 0, 0), (0, 0, *img.size))
                draw_time(img, fmt_ms(elapsed))

    def _paint_key(self, context: str) -> None:
        with self._lock:
            face = self._faces.get(context)
        if face is not None:
            self.paint(face)

    # --- ticking

    def tick(self) -> None:
        """Repaint the running keys; safe to call from any thread."""
        with self._lock:
            faces = [f for c, f in self._faces.items() if c in self._watches and self._watches[c].running]
        for face in faces:
            self.paint(face)

    def start_ticker(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def ticker_alive(self) -> bool:
        return self._ticker.alive()


_watches = Stopwatches()


def reset_for_tests() -> None:
    """Stop the ticker and forget every stopwatch and key."""
    _watches.stop()
    _watches.clear()


@card(CARD)
class StopwatchCard(DeckerPlugin):
    """A stopwatch key: press to start or pause; double or long press to reset."""

    def on_will_appear(self, ctx: CardContext) -> None:
        _watches.track(ctx)

    def on_will_disappear(self, ctx: CardContext) -> None:
        _watches.untrack(ctx)  # the stopwatch itself keeps running


def _key_of(ctx: ActionCallContext) -> Any:
    if ctx.card is None:
        raise ActionError("Stopwatch actions need a Stopwatch card")
    return ctx.card


@action("com.decker.utilities.stopwatch-toggle")
def stopwatch_toggle(ctx: ActionCallContext) -> None:
    """Start the Stopwatch, or pause it while it runs."""
    _watches.toggle(_key_of(ctx).context)


@action("com.decker.utilities.stopwatch-reset")
def stopwatch_reset(ctx: ActionCallContext) -> None:
    """Stop the Stopwatch and set it back to 0:00."""
    _watches.reset(_key_of(ctx).context)
