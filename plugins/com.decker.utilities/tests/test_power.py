"""Suspend and lock per platform, with every OS entry point replaced by a fake."""

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import power
import pytest
from assertpy import assert_that
from power import PowerError, lock, suspend

_LOGIND = ("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager")


class FakeLogind:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._error = error

    def __call__(self, path: str, interface: str, method: str, signature: str, args: tuple[Any, ...]) -> None:
        self.calls.append((path, interface, method, signature, args))
        if self._error is not None:
            raise self._error


class FakeRun:
    def __init__(self, returncode: int = 0, stderr: str = "", error: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._result = (returncode, stderr)
        self._error = error

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        if self._error is not None:
            raise self._error
        return self._result


def _windll(suspend_result: int = 1, lock_result: int = 1) -> SimpleNamespace:
    calls: list[tuple[Any, ...]] = []

    def set_suspend_state(*args: Any) -> int:
        calls.append(("SetSuspendState", *args))
        return suspend_result

    def lock_workstation() -> int:
        calls.append(("LockWorkStation",))
        return lock_result

    return SimpleNamespace(
        calls=calls,
        powrprof=SimpleNamespace(SetSuspendState=set_suspend_state),
        user32=SimpleNamespace(LockWorkStation=lock_workstation),
    )


# --- Linux


def test_linux_suspend_calls_logind_manager_suspend_without_interactive_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLogind()
    monkeypatch.setattr(power, "_logind_call", fake)

    suspend("linux")

    assert_that(fake.calls).is_equal_to(
        [("/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Suspend", "b", (False,))]
    )


def test_linux_lock_calls_the_auto_session_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLogind()
    monkeypatch.setattr(power, "_logind_call", fake)

    lock("linux")

    assert_that(fake.calls).is_equal_to(
        [("/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session", "Lock", "", ())]
    )


def test_linux_failure_is_a_power_error_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "_logind_call", FakeLogind(PowerError("logind refused: AccessDenied")))

    with pytest.raises(PowerError, match="AccessDenied"):
        suspend("linux")


class _DBusErrorResponse(Exception):
    pass


def _fake_jeepney(monkeypatch: pytest.MonkeyPatch, reply: str) -> tuple[list[str], list[Any]]:
    """A jeepney whose connection answers with ``reply``; unwrap_msg raises on an error reply, like the real one."""
    events: list[str] = []
    built: list[Any] = []

    def unwrap_msg(message: str) -> str:
        if message == "error-reply":
            raise _DBusErrorResponse("org.freedesktop.DBus.Error.AccessDenied")
        return message

    class Connection:
        def send_and_get_reply(self, message: Any, timeout: float | None = None) -> str:
            events.append("sent")
            return reply

        def close(self) -> None:
            events.append("closed")

    def new_method_call(address: Any, method: str, signature: str = "", args: tuple[Any, ...] = ()) -> str:
        built.append((address, method, signature, args))
        return "call"

    jeepney = ModuleType("jeepney")
    jeepney.DBusAddress = lambda path, bus_name, interface: (path, bus_name, interface)  # type: ignore[attr-defined]
    jeepney.new_method_call = new_method_call  # type: ignore[attr-defined]
    jeepney.unwrap_msg = unwrap_msg  # type: ignore[attr-defined]
    io = ModuleType("jeepney.io")
    blocking = ModuleType("jeepney.io.blocking")
    blocking.open_dbus_connection = lambda bus="SESSION": Connection()  # type: ignore[attr-defined]
    for name, module in {"jeepney": jeepney, "jeepney.io": io, "jeepney.io.blocking": blocking}.items():
        monkeypatch.setitem(sys.modules, name, module)
    return events, built


def test_default_logind_call_sends_the_method_on_the_system_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    events, built = _fake_jeepney(monkeypatch, "ok-reply")

    suspend("linux")

    assert_that(events).is_equal_to(["sent", "closed"])
    assert_that(built).is_equal_to([(("/org/freedesktop/login1", _LOGIND[0], _LOGIND[2]), "Suspend", "b", (False,))])


def test_default_logind_error_reply_is_a_power_error_and_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    events, _ = _fake_jeepney(monkeypatch, "error-reply")

    with pytest.raises(PowerError, match="AccessDenied"):
        suspend("linux")
    assert_that(events).is_equal_to(["sent", "closed"])


def test_default_logind_without_jeepney_is_a_readable_power_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jeepney", None)

    with pytest.raises(PowerError, match="jeepney"):
        lock("linux")


# --- Windows


def test_windows_suspend_and_lock_use_the_win32_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _windll()
    monkeypatch.setattr(power, "_windll", lambda: api)

    suspend("win32")
    lock("win32")

    assert_that(api.calls).is_equal_to([("SetSuspendState", 0, 0, 0), ("LockWorkStation",)])


def test_windows_zero_result_is_a_power_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "_windll", lambda: _windll(suspend_result=0, lock_result=0))

    with pytest.raises(PowerError, match="suspend"):
        suspend("win32")
    with pytest.raises(PowerError, match="lock"):
        lock("win32")


@pytest.mark.skipif(sys.platform == "win32", reason="ctypes.windll exists on Windows")
def test_windows_api_unavailable_is_a_power_error() -> None:
    with pytest.raises(PowerError, match="Windows"):
        power._windll()


# --- macOS


def test_macos_suspend_runs_pmset_sleepnow(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun()
    monkeypatch.setattr(power, "_run", fake)

    suspend("darwin")

    assert_that(fake.calls).is_equal_to([["pmset", "sleepnow"]])


def test_macos_lock_sends_the_lock_screen_shortcut(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun()
    monkeypatch.setattr(power, "_run", fake)

    lock("darwin")

    assert_that(fake.calls).is_equal_to(
        [["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}']]
    )


def test_macos_lock_failure_mentions_accessibility_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "_run", FakeRun(1, "not allowed to send keystrokes"))

    with pytest.raises(PowerError, match="Accessibility") as info:
        lock("darwin")
    assert_that(str(info.value)).contains("not allowed to send keystrokes")


def test_macos_suspend_failure_carries_the_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "_run", FakeRun(1, "pmset: boom"))

    with pytest.raises(PowerError, match="pmset: boom"):
        suspend("darwin")


def test_macos_missing_command_is_a_power_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "_run", FakeRun(error=PowerError("pmset not found")))

    with pytest.raises(PowerError, match="not found"):
        suspend("darwin")


def test_default_run_turns_a_missing_command_into_a_power_error() -> None:
    with pytest.raises(PowerError, match="no-such-command-xyz"):
        power._run(["no-such-command-xyz"])


# --- anywhere


def test_an_unsupported_platform_is_a_power_error() -> None:
    with pytest.raises(PowerError, match="plan9"):
        suspend("plan9")
    with pytest.raises(PowerError, match="plan9"):
        lock("plan9")
