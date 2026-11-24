"""Display brightness: per-platform backends behind one interface, plus a polling cache.

Backends do blocking I/O (sysfs, D-Bus, ddcutil, DisplayServices), so they must only run off the plugin message
loop: ``BrightnessCache`` owns the polling thread, and callers of ``BrightnessCache.change`` run it off the loop too.
``jeepney``, ``screen_brightness_control`` and the macOS frameworks are imported lazily, only on the platform that
uses them, so this module imports cleanly everywhere.
"""

import hashlib
import logging
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

_log = logging.getLogger(__name__)

_SYSFS_BACKLIGHT = Path("/sys/class/backlight")


@dataclass(frozen=True)
class Monitor:
    id: str
    name: str


class BrightnessError(Exception):
    """A brightness read or write failed; the message is safe to show the user."""


class Backend(Protocol):
    def list_monitors(self) -> list[Monitor]: ...

    def get(self, monitor_id: str) -> int: ...

    def set(self, monitor_id: str, percent: int) -> None: ...


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _send_logind(subsystem: str, name: str, raw: int) -> None:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection

    address = DBusAddress(
        "/org/freedesktop/login1/session/auto",
        bus_name="org.freedesktop.login1",
        interface="org.freedesktop.login1.Session",
    )
    message = new_method_call(address, "SetBrightness", "ssu", (subsystem, name, raw))
    connection = open_dbus_connection(bus="SYSTEM")
    try:
        connection.send_and_get_reply(message, timeout=5)
    finally:
        connection.close()


class LogindBacklight:
    """Linux internal panel: reads sysfs, writes through logind so no root is needed."""

    prefixes = ("backlight:",)
    _PREFIX = "backlight:"

    def __init__(self, root: Path = _SYSFS_BACKLIGHT, sender: Callable[[str, str, int], None] = _send_logind) -> None:
        self._root = root
        self._send = sender

    def list_monitors(self) -> list[Monitor]:
        if not self._root.is_dir():
            return []
        return [Monitor(self._PREFIX + p.name, p.name) for p in sorted(self._root.iterdir()) if p.is_dir()]

    def get(self, monitor_id: str) -> int:
        name = self._device(monitor_id)
        maximum = self._read(monitor_id, name, "max_brightness")
        if maximum <= 0:
            return 0
        return _clamp(round(self._read(monitor_id, name, "brightness") * 100 / maximum))

    def set(self, monitor_id: str, percent: int) -> None:
        name = self._device(monitor_id)
        maximum = self._read(monitor_id, name, "max_brightness")
        if maximum <= 0:
            raise BrightnessError(f"monitor {monitor_id} reports no brightness range")
        percent = _clamp(percent)
        raw = round(percent * maximum / 100)
        if percent > 0:
            raw = max(raw, 1)  # a positive level must never round down to a dark panel
        try:
            self._send("backlight", name, raw)
        except Exception as exc:
            raise BrightnessError(f"could not set monitor {monitor_id}: {exc}") from exc

    def _device(self, monitor_id: str) -> str:
        name = monitor_id.removeprefix(self._PREFIX)
        if not monitor_id.startswith(self._PREFIX) or not (self._root / name).is_dir():
            raise BrightnessError(f"monitor {monitor_id} not found")
        return name

    def _read(self, monitor_id: str, name: str, field: str) -> int:
        try:
            return int((self._root / name / field).read_text().strip())
        except (OSError, ValueError) as exc:
            raise BrightnessError(f"could not read monitor {monitor_id}: {exc}") from exc


class SbcBackend:
    """External monitors (DDC/CI on Linux via ddcutil, all methods on Windows) through screen_brightness_control."""

    def __init__(self, platform: str = sys.platform, module: Any = None) -> None:
        self._platform = platform
        self._module = module
        self._method = "ddcutil" if platform.startswith("linux") else None
        self._prefix = "win:" if platform == "win32" else "ddc:"
        self.prefixes = (self._prefix,)

    def list_monitors(self) -> list[Monitor]:
        return [Monitor(monitor_id, str(info.get("name") or monitor_id)) for monitor_id, info, _ in self._entries()]

    def get(self, monitor_id: str) -> int:
        sbc = self._sbc()
        display = self._display(monitor_id)
        try:
            levels = sbc.get_brightness(display=display, method=self._method)
        except Exception as exc:
            raise BrightnessError(f"could not read monitor {monitor_id}: {exc}") from exc
        if not levels or levels[0] is None:
            raise BrightnessError(f"could not read monitor {monitor_id}")
        return _clamp(int(levels[0]))

    def set(self, monitor_id: str, percent: int) -> None:
        sbc = self._sbc()
        display = self._display(monitor_id)
        try:
            sbc.set_brightness(_clamp(percent), display=display, method=self._method)
        except Exception as exc:
            raise BrightnessError(f"could not set monitor {monitor_id}: {exc}") from exc

    def _sbc(self) -> Any:
        if self._module is None:
            try:
                import screen_brightness_control
            except ImportError as exc:
                raise BrightnessError("screen_brightness_control is not installed") from exc
            self._module = screen_brightness_control
        return self._module

    def _entries(self) -> list[tuple[str, dict[str, Any], Any]]:
        try:
            infos = self._sbc().list_monitors_info(method=self._method)
        except BrightnessError:
            raise
        except Exception as exc:
            raise BrightnessError(f"could not list monitors: {exc}") from exc
        entries = []
        for info in infos:
            serial = info.get("serial")
            edid = info.get("edid")
            if serial:
                key, display = str(serial), str(serial)
            elif self._platform == "win32" or not edid:
                key, display = str(info.get("index", 0)), info.get("index", 0)
            else:
                key, display = hashlib.sha1(str(edid).encode()).hexdigest()[:12], str(edid)
            entries.append((self._prefix + key, info, display))
        return entries

    def _display(self, monitor_id: str) -> Any:
        for entry_id, _, display in self._entries():
            if entry_id == monitor_id:
                return display
        raise BrightnessError(f"monitor {monitor_id} not found")


class _DisplayServices:
    """DisplayServices (private framework) brightness of the main display, through ctypes."""

    def __init__(self) -> None:
        import ctypes

        services = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
        graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        graphics.CGMainDisplayID.restype = ctypes.c_uint32
        services.DisplayServicesGetBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        services.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        self._ctypes = ctypes
        self._services = services
        self._display = graphics.CGMainDisplayID()

    def get(self) -> float:
        value = self._ctypes.c_float()
        if self._services.DisplayServicesGetBrightness(self._display, self._ctypes.byref(value)) != 0:
            raise BrightnessError("DisplayServices could not read the brightness")
        return value.value

    def set(self, value: float) -> None:
        if self._services.DisplayServicesSetBrightness(self._display, value) != 0:
            raise BrightnessError("DisplayServices could not set the brightness")


class MacInternal:
    """macOS built-in display. ``api`` (get() -> 0..1, set(float)) is injectable; by default it is loaded lazily."""

    prefixes = ("mac:",)
    _ID = "mac:internal"

    def __init__(self, api: Any = None) -> None:
        self._api = api

    def list_monitors(self) -> list[Monitor]:
        if self._api is None and sys.platform != "darwin":
            return []
        return [Monitor(self._ID, "Built-in display")]

    def get(self, monitor_id: str) -> int:
        return _clamp(round(self._service(monitor_id).get() * 100))

    def set(self, monitor_id: str, percent: int) -> None:
        self._service(monitor_id).set(_clamp(percent) / 100)

    def _service(self, monitor_id: str) -> Any:
        if monitor_id != self._ID:
            raise BrightnessError(f"monitor {monitor_id} not found")
        if self._api is None:
            try:
                self._api = _DisplayServices()
            except (OSError, ImportError, AttributeError) as exc:
                raise BrightnessError(f"DisplayServices is unavailable: {exc}") from exc
        return self._api


class CompositeBackend:
    """Concatenates child backends and routes each monitor id to the child that owns its prefix."""

    def __init__(self, children: list[Any]) -> None:
        self._children = children
        self._reported: set[int] = set()
        self.prefixes = tuple(p for child in children for p in getattr(child, "prefixes", ()))

    def list_monitors(self) -> list[Monitor]:
        monitors: list[Monitor] = []
        for index, child in enumerate(self._children):
            try:
                monitors.extend(child.list_monitors())
            except Exception as exc:
                if index not in self._reported:
                    self._reported.add(index)
                    _log.warning("brightness backend %s failed to list monitors: %s", type(child).__name__, exc)
        return monitors

    def get(self, monitor_id: str) -> int:
        return int(self._child(monitor_id).get(monitor_id))

    def set(self, monitor_id: str, percent: int) -> None:
        self._child(monitor_id).set(monitor_id, percent)

    def _child(self, monitor_id: str) -> Any:
        for child in self._children:
            if monitor_id.startswith(tuple(getattr(child, "prefixes", ()))):
                return child
        raise BrightnessError(f"monitor {monitor_id} not found")


def default_backend(platform: str = sys.platform) -> Backend:
    if platform.startswith("linux"):
        return CompositeBackend([LogindBacklight(), SbcBackend(platform)])
    if platform == "win32":
        return SbcBackend(platform)
    if platform == "darwin":
        return MacInternal()
    return CompositeBackend([])


def label_monitors(monitors: list[Monitor]) -> list[tuple[str, str]]:
    """(id, label) pairs; repeated names get " (2)", " (3)" so options stay distinguishable."""
    seen: dict[str, int] = {}
    labels = []
    for monitor in monitors:
        seen[monitor.name] = seen.get(monitor.name, 0) + 1
        count = seen[monitor.name]
        labels.append((monitor.id, monitor.name if count == 1 else f"{monitor.name} ({count})"))
    return labels


class BrightnessCache:
    """Last known brightness per monitor, refreshed by a background thread every ``interval`` seconds."""

    def __init__(self, backend: Backend, interval: float = 5.0, on_change: Callable[[], None] | None = None) -> None:
        self._backend = backend
        self._interval = interval
        self._on_change = on_change
        self._lock = threading.Lock()
        self._monitors: list[Monitor] = []
        self._levels: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="brightness-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None:
            thread.join()

    def monitors(self) -> list[Monitor]:
        with self._lock:
            return list(self._monitors)

    def level(self, monitor_id: str) -> int | None:
        with self._lock:
            return self._levels.get(monitor_id)

    def average(self) -> int | None:
        with self._lock:
            if not self._levels:
                return None
            return round(sum(self._levels.values()) / len(self._levels))

    def poll_once(self) -> None:
        """Refresh from the backend; calls ``on_change`` (outside the lock) when monitors or levels differ."""
        try:
            monitors = self._backend.list_monitors()
        except Exception as exc:
            _log.warning("brightness poll could not list monitors: %s", exc)
            return
        levels: dict[str, int] = {}
        for monitor in monitors:
            try:
                levels[monitor.id] = self._backend.get(monitor.id)
            except Exception as exc:
                _log.debug("brightness poll could not read %s: %s", monitor.id, exc)
        with self._lock:
            changed = monitors != self._monitors or levels != self._levels
            self._monitors, self._levels = monitors, levels
        if changed:
            self._notify()

    def change(
        self, monitor_id: str | Literal["all"], mode: Literal["increase", "decrease", "set"], value: int
    ) -> dict[str, int]:
        """Apply the change and return the new levels by id. Blocks on hardware: call it off the message loop.

        With "all" every monitor is attempted; the failures are reported together afterwards.
        """
        if not self.monitors():
            self.poll_once()
        monitors = self.monitors()
        if not monitors:
            raise BrightnessError("no monitor found")
        targets = [m.id for m in monitors] if monitor_id == "all" else [monitor_id]
        if monitor_id != "all" and monitor_id not in {m.id for m in monitors}:
            raise BrightnessError(f"monitor {monitor_id} not found")
        applied: dict[str, int] = {}
        failures: list[str] = []
        for target in targets:
            try:
                applied[target] = self._apply(target, mode, value)
            except BrightnessError as exc:
                failures.append(str(exc))
        if applied:
            with self._lock:
                self._levels.update(applied)
            self._notify()
        if failures:
            raise BrightnessError("; ".join(failures))
        return applied

    def _apply(self, monitor_id: str, mode: str, value: int) -> int:
        if mode == "set":
            new = _clamp(value)
        else:
            current = self.level(monitor_id)
            if current is None:
                current = self._backend.get(monitor_id)
            new = _clamp(current + value if mode == "increase" else current - value)
        self._backend.set(monitor_id, new)
        return new

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._interval)

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()
