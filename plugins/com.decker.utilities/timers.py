"""Countdown and Timer arithmetic and time formatting shared by the Sleep card and the timer cards."""

import sys
import time
from collections.abc import Callable
from typing import Literal


def sleep_inclusive_clock() -> float:
    """Seconds on a clock that keeps counting while the machine is suspended (the one clock timers measure on).

    Linux: CLOCK_BOOTTIME. macOS: CLOCK_MONOTONIC, which counts through sleep there. Windows: ``time.monotonic``, which
    does too. Anything else falls back to wall time.
    """
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    if sys.platform == "darwin":
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    if sys.platform == "win32":
        return time.monotonic()
    return time.time()


class Countdown:
    """Time left until a deadline on an injectable monotonic clock.

    The monotonic clock stops while the machine sleeps (Linux, macOS), so a second clock that keeps counting through
    sleep stores the same deadline; ``overdue`` measures on it how late the countdown really is.
    """

    def __init__(
        self,
        seconds: float,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = sleep_inclusive_clock,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self.deadline = clock() + seconds
        self._wall_deadline = wall_clock() + seconds

    def remaining(self) -> float:
        """Seconds left, never below 0."""
        return max(0.0, self.deadline - self._clock())

    def overdue(self) -> float:
        """Seconds past the deadline on the sleep-inclusive clock (negative while it is still ahead)."""
        return self._wall_clock() - self._wall_deadline

    def expired(self) -> bool:
        return self.remaining() <= 0


TimerState = Literal["idle", "running", "paused", "finished"]
_GRACE_SECONDS = 5.0  # a timer found this far past its end finished unseen; it does not ring


class Timer:
    """A pausable timer on an injectable clock; the card drives it with ``tick``.

    It measures elapsed time on one clock that keeps counting while the machine sleeps (``sleep_inclusive_clock``), so
    its remaining time is always real time. A timer whose end falls inside a system sleep is finished at the wake and
    shows 0:00; if that is more than the grace past its end, ``tick`` finishes it quietly instead of ringing late.
    """

    def __init__(
        self, duration: float, clock: Callable[[], float] = sleep_inclusive_clock, grace: float = _GRACE_SECONDS
    ) -> None:
        self.duration = duration
        self.state: TimerState = "idle"
        self._clock = clock
        self._grace = grace
        self._started = 0.0
        self._elapsed = 0.0  # run time of the finished stretches (before the last pause)

    def toggle(self) -> None:
        """Idle starts, running pauses, paused resumes, finished restarts from the full duration."""
        if self.state == "running":
            self._elapsed = self._run_time()
            self.state = "paused"
            return
        if self.state in ("idle", "finished"):
            self._elapsed = 0.0
        self._started = self._clock()
        self.state = "running"

    def reset(self) -> None:
        self.state = "idle"
        self._elapsed = 0.0

    def remaining(self) -> float:
        """Seconds left, between 0 and the duration."""
        if self.state == "finished":
            return 0.0
        return max(0.0, self.duration - self._run_time())

    def fraction_left(self) -> float:
        """Share of the duration left, 0 to 1 (0 for a zero duration)."""
        return self.remaining() / self.duration if self.duration > 0 else 0.0

    def tick(self) -> bool:
        """Finish a running timer that ran out; True only when it ends now, not when it is found long past its end."""
        if self.state != "running" or self.remaining() > 0:
            return False
        late = self._run_time() - self.duration
        self.state = "finished"
        return late <= self._grace

    def _run_time(self) -> float:
        if self.state == "running":
            return self._elapsed + self._clock() - self._started
        return self._elapsed


class Stopwatch:
    """Counts up while running, on one clock that keeps counting through a system sleep (like ``Timer``)."""

    def __init__(self, clock: Callable[[], float] = sleep_inclusive_clock) -> None:
        self._clock = clock
        self.running = False
        self._started = 0.0
        self._elapsed = 0.0  # run time of the finished stretches (before the last pause)

    def toggle(self) -> None:
        """Start or resume a stopped stopwatch, pause a running one."""
        if self.running:
            self._elapsed = self.elapsed()
            self.running = False
        else:
            self._started = self._clock()
            self.running = True

    def reset(self) -> None:
        self.running = False
        self._elapsed = 0.0

    def elapsed(self) -> float:
        """Seconds run so far."""
        return self._elapsed + self._clock() - self._started if self.running else self._elapsed


def fmt_ms(seconds: float) -> str:
    """``m:ss``, or ``h:mm:ss`` from one hour; whole seconds, negative counts as 0."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
