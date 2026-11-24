"""Suspend and lock the computer, per platform.

Linux asks systemd-logind over D-Bus (``jeepney``), Windows calls ``powrprof``/``user32`` through ctypes and macOS runs
``pmset``/``osascript``. All three calls block, so callers run them off the plugin message loop. Everything platform
specific is imported lazily and sits behind ``_logind_call``, ``_windll`` and ``_run``, so this module imports on any OS
and tests replace those three. Every failure is a ``PowerError`` with a readable message.
"""

import subprocess
import sys
from typing import Any

_LOGIND_BUS = "org.freedesktop.login1"
_MANAGER = ("/org/freedesktop/login1", "org.freedesktop.login1.Manager")
_SESSION = ("/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session")
_LOCK_SCRIPT = 'tell application "System Events" to keystroke "q" using {control down, command down}'
_DBUS_TIMEOUT = 5
_COMMAND_TIMEOUT = 15


class PowerError(Exception):
    """Suspending or locking failed; the message says why."""


def _logind_call(path: str, interface: str, method: str, signature: str, args: tuple[Any, ...]) -> None:
    try:
        from jeepney import DBusAddress, new_method_call, unwrap_msg
        from jeepney.io.blocking import open_dbus_connection
    except ImportError as exc:
        raise PowerError("the jeepney package is not installed, so systemd-logind cannot be reached") from exc
    address = DBusAddress(path, bus_name=_LOGIND_BUS, interface=interface)
    message = new_method_call(address, method, signature or None, args)
    try:
        connection = open_dbus_connection(bus="SYSTEM")
        try:
            # send_and_get_reply returns error replies instead of raising; unwrap_msg raises on them
            unwrap_msg(connection.send_and_get_reply(message, timeout=_DBUS_TIMEOUT))
        finally:
            connection.close()
    except Exception as exc:
        raise PowerError(f"systemd-logind refused {method}: {exc}") from exc


def _windll() -> Any:
    import ctypes

    try:
        return ctypes.windll  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise PowerError("the Windows power API is only available on Windows") from exc


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=_COMMAND_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PowerError(f"could not run {argv[0]}: {exc}") from exc
    return done.returncode, done.stderr.strip()


def _run_checked(argv: list[str], failure: str) -> None:
    code, stderr = _run(argv)
    if code != 0:
        raise PowerError(f"{failure}: {stderr or f'{argv[0]} exited with {code}'}")


def _windows_call(which: str, func_name: str, *args: int) -> None:
    api = _windll()
    func = getattr(getattr(api, which), func_name)
    if not func(*args):
        raise PowerError(f"Windows could not {'suspend the PC' if func_name == 'SetSuspendState' else 'lock the PC'}")


def _unsupported(platform: str) -> PowerError:
    return PowerError(f"suspend and lock are not supported on {platform!r}")


def suspend(platform: str = sys.platform) -> None:
    """Put the computer to sleep."""
    if platform.startswith("linux"):
        _logind_call(*_MANAGER, "Suspend", "b", (False,))
    elif platform == "win32":
        _windows_call("powrprof", "SetSuspendState", 0, 0, 0)
    elif platform == "darwin":
        _run_checked(["pmset", "sleepnow"], "pmset could not put the Mac to sleep")
    else:
        raise _unsupported(platform)


def lock(platform: str = sys.platform) -> None:
    """Lock the screen."""
    if platform.startswith("linux"):
        _logind_call(*_SESSION, "Lock", "", ())
    elif platform == "win32":
        _windows_call("user32", "LockWorkStation")
    elif platform == "darwin":
        _run_checked(
            ["osascript", "-e", _LOCK_SCRIPT],
            "could not lock the screen; Decker (or the terminal running it) needs Accessibility permission to send "
            "the lock shortcut",
        )
    else:
        raise _unsupported(platform)
