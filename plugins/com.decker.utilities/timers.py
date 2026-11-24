"""Countdown arithmetic and time formatting shared by the Sleep card and the timer cards."""

import time
from collections.abc import Callable


class Countdown:
    """Time left until a deadline on an injectable monotonic clock.

    The monotonic clock stops while the machine sleeps (Linux, macOS), so a second clock that keeps counting through
    sleep stores the same deadline; ``overdue`` measures on it how late the countdown really is.
    """

    def __init__(
        self,
        seconds: float,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
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


def fmt_ms(seconds: float) -> str:
    """``m:ss``, or ``h:mm:ss`` from one hour; whole seconds, negative counts as 0."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
