"""A lazily started daemon thread that calls a function at a fixed interval (shared by the Sleep and Timer cards).

It is not an SDK ``@main``: the SDK runs mains one after another and the brightness main never returns.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

_log = logging.getLogger(__name__)
_STOP_JOIN_SECONDS = 5.0


@dataclass
class _Run:
    thread: threading.Thread
    stop: threading.Event


class Ticker:
    """Calls ``fn`` every ``interval`` seconds on one daemon thread; start and stop are idempotent and thread-safe."""

    def __init__(self, interval: float, fn: Callable[[], None], name: str) -> None:
        self._interval = interval
        self._fn = fn
        self._name = name
        self._lifecycle = threading.Lock()  # start and stop are check-then-act on _run
        self._run: _Run | None = None

    def start(self) -> None:
        with self._lifecycle:
            if self._run is not None:
                return
            stop = threading.Event()
            thread = threading.Thread(target=self._loop, args=(stop,), name=self._name, daemon=True)
            thread.start()
            self._run = _Run(thread, stop)  # published only once it runs, so stop() never joins an unstarted one

    def stop(self) -> None:
        with self._lifecycle:
            run, self._run = self._run, None
            if run is None:
                return
            run.stop.set()
            if run.thread is not threading.current_thread():
                run.thread.join(_STOP_JOIN_SECONDS)

    def alive(self) -> bool:
        with self._lifecycle:
            return self._run is not None and self._run.thread.is_alive()

    def _loop(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            try:
                self._fn()
            except Exception:
                _log.exception("%s failed", self._name)
