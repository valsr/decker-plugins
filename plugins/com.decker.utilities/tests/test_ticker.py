"""The shared ticker lifecycle: lazy start, idempotent start and stop, self-stop, restart, the start/stop race."""

import sys
import threading
from pathlib import Path

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent.parent))
from ticker import Ticker  # noqa: E402

_WAIT = 5
_NAME = "test-ticker"


def _threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == _NAME and t.is_alive()]


def test_a_new_ticker_is_not_running() -> None:
    ticker = Ticker(0.01, lambda: None, _NAME)

    assert_that(ticker.alive()).is_false()
    assert_that(_threads()).is_empty()


def test_the_function_runs_repeatedly_until_stopped() -> None:
    calls = threading.Semaphore(0)
    ticker = Ticker(0.001, calls.release, _NAME)
    ticker.start()
    try:
        for _ in range(3):
            assert_that(calls.acquire(timeout=_WAIT)).is_true()
    finally:
        ticker.stop()

    assert_that(ticker.alive()).is_false()
    assert_that(_threads()).is_empty()


def test_start_is_idempotent_and_stop_may_be_repeated() -> None:
    ticker = Ticker(3600, lambda: None, _NAME)
    ticker.start()
    ticker.start()
    assert_that(_threads()).is_length(1)

    ticker.stop()
    ticker.stop()

    assert_that(_threads()).is_empty()


def test_a_stopped_ticker_can_start_again() -> None:
    ticker = Ticker(3600, lambda: None, _NAME)
    ticker.start()
    ticker.stop()

    ticker.start()
    try:
        assert_that(ticker.alive()).is_true()
        assert_that(_threads()).is_length(1)
    finally:
        ticker.stop()


def test_a_failing_function_is_logged_and_the_ticker_keeps_going(caplog: pytest.LogCaptureFixture) -> None:
    calls = threading.Semaphore(0)

    def boom() -> None:
        calls.release()
        raise ValueError("nope")

    ticker = Ticker(0.001, boom, _NAME)
    ticker.start()
    try:
        for _ in range(2):
            assert_that(calls.acquire(timeout=_WAIT)).is_true()
    finally:
        ticker.stop()

    assert_that(caplog.text).contains(_NAME)


def test_stop_from_the_ticker_thread_does_not_join_itself() -> None:
    errors: list[BaseException] = []
    done = threading.Event()
    holder: list[Ticker] = []

    def fn() -> None:
        try:
            holder[0].stop()
        except BaseException as exc:  # noqa: BLE001 - the test reports any failure
            errors.append(exc)
        done.set()

    ticker = Ticker(0.001, fn, _NAME)
    holder.append(ticker)
    ticker.start()

    assert_that(done.wait(_WAIT)).is_true()
    assert_that(errors).is_empty()
    ticker.stop()
    assert_that(ticker.alive()).is_false()


def test_a_stop_during_start_waits_for_the_thread_to_be_running(monkeypatch: pytest.MonkeyPatch) -> None:
    real_thread = threading.Thread
    published, stopping, errors = threading.Event(), threading.Event(), []

    class SlowStart(real_thread):  # type: ignore[misc, valid-type]
        def start(self) -> None:
            if self.name == _NAME:
                published.set()
                stopping.wait(_WAIT)  # a window in which stop() could see the thread before it was started
            super().start()

    ticker = Ticker(0.05, lambda: None, _NAME)

    def stopper() -> None:
        assert published.wait(_WAIT)
        stopping.set()
        try:
            ticker.stop()
        except RuntimeError as exc:
            errors.append(exc)

    stop_thread = real_thread(target=stopper)
    stop_thread.start()
    monkeypatch.setattr(threading, "Thread", SlowStart)
    ticker.start()
    monkeypatch.undo()
    stop_thread.join(_WAIT)

    assert_that(errors).is_empty()
    assert_that(ticker.alive()).is_false()
