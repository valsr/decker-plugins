"""Brightness backends and cache, against fakes: a sysfs tree, a D-Bus sender, a screen_brightness_control stub."""

import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from assertpy import assert_that

sys.path.insert(0, str(Path(__file__).parent.parent))
from brightness import (  # noqa: E402
    BrightnessCache,
    BrightnessError,
    CompositeBackend,
    LogindBacklight,
    MacInternal,
    Monitor,
    SbcBackend,
    default_backend,
    label_monitors,
)


def _sysfs(root: Path, name: str, raw: int, maximum: int) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "brightness").write_text(f"{raw}\n")
    (root / name / "max_brightness").write_text(f"{maximum}\n")


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, subsystem: str, name: str, raw: int) -> None:
        self.calls.append((subsystem, name, raw))


class FakeBackend:
    prefixes = ("fake:",)

    def __init__(self, levels: dict[str, int], fail_set: set[str] | None = None) -> None:
        self.levels = dict(levels)
        self.fail_set = fail_set or set()
        self.vanished: set[str] = set()

    def list_monitors(self) -> list[Monitor]:
        return [Monitor(i, i.upper()) for i in self.levels if i not in self.vanished]

    def get(self, monitor_id: str) -> int:
        if monitor_id in self.vanished or monitor_id not in self.levels:
            raise BrightnessError(f"monitor {monitor_id} is gone")
        return self.levels[monitor_id]

    def set(self, monitor_id: str, percent: int) -> None:
        if monitor_id in self.fail_set or monitor_id in self.vanished:
            raise BrightnessError(f"monitor {monitor_id} is gone")
        self.levels[monitor_id] = percent


# --- LogindBacklight


def test_logind_lists_and_converts_raw_to_percent(tmp_path: Path) -> None:
    _sysfs(tmp_path, "intel_backlight", 120, 480)
    backend = LogindBacklight(tmp_path, FakeSender())

    assert_that(backend.list_monitors()).is_equal_to([Monitor("backlight:intel_backlight", "intel_backlight")])
    assert_that(backend.get("backlight:intel_backlight")).is_equal_to(25)


def test_logind_set_converts_percent_to_rounded_raw(tmp_path: Path) -> None:
    _sysfs(tmp_path, "bl", 0, 255)
    sender = FakeSender()
    LogindBacklight(tmp_path, sender).set("backlight:bl", 50)

    assert_that(sender.calls).is_equal_to([("backlight", "bl", 128)])


def test_logind_positive_percent_floor_is_one_raw_step(tmp_path: Path) -> None:
    _sysfs(tmp_path, "big", 10, 1000)
    sender = FakeSender()
    LogindBacklight(tmp_path, sender).set("backlight:big", 0)
    _sysfs(tmp_path, "tiny", 0, 3)
    LogindBacklight(tmp_path, sender).set("backlight:tiny", 10)

    assert_that(sender.calls).is_equal_to([("backlight", "big", 0), ("backlight", "tiny", 1)])


def test_logind_zero_max_brightness_is_guarded(tmp_path: Path) -> None:
    _sysfs(tmp_path, "bl", 0, 0)
    sender = FakeSender()
    backend = LogindBacklight(tmp_path, sender)

    assert_that(backend.get("backlight:bl")).is_equal_to(0)
    with pytest.raises(BrightnessError):
        backend.set("backlight:bl", 50)
    assert_that(sender.calls).is_empty()


def test_logind_missing_root_lists_nothing_and_unknown_id_errors(tmp_path: Path) -> None:
    backend = LogindBacklight(tmp_path / "nope", FakeSender())

    assert_that(backend.list_monitors()).is_empty()
    with pytest.raises(BrightnessError, match="backlight:gone"):
        backend.get("backlight:gone")
    with pytest.raises(BrightnessError, match="backlight:gone"):
        backend.set("backlight:gone", 10)


def test_logind_sender_failure_becomes_brightness_error(tmp_path: Path) -> None:
    _sysfs(tmp_path, "bl", 1, 100)

    def boom(subsystem: str, name: str, raw: int) -> None:
        raise OSError("dbus down")

    with pytest.raises(BrightnessError, match="backlight:bl"):
        LogindBacklight(tmp_path, boom).set("backlight:bl", 10)


# --- SbcBackend


def _sbc(infos: list[dict[str, Any]], levels: dict[str, int]) -> SimpleNamespace:
    calls: list[tuple[int, Any, str | None]] = []

    def list_monitors_info(method: str | None = None) -> list[dict[str, Any]]:
        return infos

    def get_brightness(display: Any = None, method: str | None = None) -> list[int]:
        return [levels[display]]

    def set_brightness(value: int, display: Any = None, method: str | None = None) -> None:
        calls.append((value, display, method))
        levels[display] = value

    return SimpleNamespace(
        list_monitors_info=list_monitors_info, get_brightness=get_brightness, set_brightness=set_brightness, calls=calls
    )


def test_sbc_linux_uses_ddcutil_and_serial_ids() -> None:
    sbc = _sbc([{"name": "Dell U2720Q", "serial": "ABC123", "edid": "00ff", "index": 0}], {"ABC123": 40})
    backend = SbcBackend("linux", module=sbc)

    assert_that(backend.list_monitors()).is_equal_to([Monitor("ddc:ABC123", "Dell U2720Q")])
    assert_that(backend.get("ddc:ABC123")).is_equal_to(40)
    backend.set("ddc:ABC123", 70)
    assert_that(sbc.calls).is_equal_to([(70, "ABC123", "ddcutil")])


def test_sbc_without_serial_hashes_the_edid() -> None:
    sbc = _sbc([{"name": "X", "serial": None, "edid": "00ffff00", "index": 0}], {})
    monitor = SbcBackend("linux", module=sbc).list_monitors()[0]

    assert_that(monitor.id).matches(r"^ddc:[0-9a-f]{12}$")


def test_sbc_windows_ids_use_serial_or_index() -> None:
    sbc = _sbc([{"name": "A", "serial": "S1", "index": 0}, {"name": "B", "serial": None, "index": 1}], {})

    assert_that([m.id for m in SbcBackend("win32", module=sbc).list_monitors()]).is_equal_to(["win:S1", "win:1"])


def test_sbc_vanished_monitor_is_a_clear_error() -> None:
    sbc = _sbc([], {})

    with pytest.raises(BrightnessError, match="ddc:ABC"):
        SbcBackend("linux", module=sbc).set("ddc:ABC", 10)
    with pytest.raises(BrightnessError, match="ddc:ABC"):
        SbcBackend("linux", module=sbc).get("ddc:ABC")


def test_sbc_library_errors_become_brightness_errors() -> None:
    def explode(method: str | None = None) -> list[dict[str, Any]]:
        raise RuntimeError("ddcutil missing")

    with pytest.raises(BrightnessError, match="ddcutil missing"):
        SbcBackend("linux", module=SimpleNamespace(list_monitors_info=explode)).list_monitors()


# --- MacInternal


def test_mac_internal_converts_float_scale() -> None:
    state = {"v": 0.5}
    api = SimpleNamespace(get=lambda: state["v"], set=lambda v: state.update(v=v))
    backend = MacInternal(api=api)

    assert_that(backend.list_monitors()).is_equal_to([Monitor("mac:internal", "Built-in display")])
    assert_that(backend.get("mac:internal")).is_equal_to(50)
    backend.set("mac:internal", 25)
    assert_that(state["v"]).is_close_to(0.25, 1e-9)
    with pytest.raises(BrightnessError):
        backend.get("mac:other")


def test_mac_internal_without_api_lists_nothing_off_darwin() -> None:
    assert_that(MacInternal().list_monitors()).is_empty()


# --- CompositeBackend / default_backend / labels


def test_composite_concatenates_and_routes_by_prefix() -> None:
    a = FakeBackend({"fake:1": 10})
    b = FakeBackend({"other:1": 20})
    b.prefixes = ("other:",)
    composite = CompositeBackend([a, b])

    assert_that([m.id for m in composite.list_monitors()]).is_equal_to(["fake:1", "other:1"])
    assert_that(composite.get("other:1")).is_equal_to(20)
    composite.set("fake:1", 90)
    assert_that(a.levels["fake:1"]).is_equal_to(90)
    with pytest.raises(BrightnessError, match="zzz:1"):
        composite.get("zzz:1")


def test_composite_skips_a_failing_child_and_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    class Broken(FakeBackend):
        def list_monitors(self) -> list[Monitor]:
            raise BrightnessError("nope")

    composite = CompositeBackend([Broken({}), FakeBackend({"fake:1": 5})])
    with caplog.at_level("WARNING"):
        first = composite.list_monitors()
        second = composite.list_monitors()

    assert_that(first).is_equal_to(second).is_length(1)
    assert_that([r for r in caplog.records if "nope" in r.getMessage()]).is_length(1)


def test_default_backend_per_platform() -> None:
    assert_that(default_backend("linux")).is_instance_of(CompositeBackend)
    assert_that(default_backend("win32")).is_instance_of(SbcBackend)
    assert_that(default_backend("darwin")).is_instance_of(MacInternal)
    assert_that(default_backend("freebsd").list_monitors()).is_empty()


def test_label_monitors_numbers_duplicate_names() -> None:
    monitors = [Monitor("a", "Dell"), Monitor("b", "HP"), Monitor("c", "Dell"), Monitor("d", "Dell")]

    assert_that(label_monitors(monitors)).is_equal_to(
        [("a", "Dell"), ("b", "HP"), ("c", "Dell (2)"), ("d", "Dell (3)")]
    )


# --- BrightnessCache


def test_cache_empty_monitor_list_is_no_monitor_found() -> None:
    cache = BrightnessCache(FakeBackend({}))

    assert_that(cache.average()).is_none()
    with pytest.raises(BrightnessError, match="no monitor found"):
        cache.change("all", "set", 50)


def test_cache_change_modes_and_clamping() -> None:
    backend = FakeBackend({"fake:1": 95})
    cache = BrightnessCache(backend)
    cache.poll_once()

    assert_that(cache.change("fake:1", "increase", 10)).is_equal_to({"fake:1": 100})
    assert_that(cache.change("fake:1", "decrease", 250)).is_equal_to({"fake:1": 0})
    assert_that(cache.change("fake:1", "set", 33)).is_equal_to({"fake:1": 33})
    assert_that(cache.level("fake:1")).is_equal_to(33)
    assert_that(backend.levels["fake:1"]).is_equal_to(33)


def test_cache_change_polls_when_not_yet_populated() -> None:
    cache = BrightnessCache(FakeBackend({"fake:1": 10}))

    assert_that(cache.change("fake:1", "increase", 5)).is_equal_to({"fake:1": 15})


def test_cache_all_partial_failure_sets_the_rest_and_names_the_failed() -> None:
    backend = FakeBackend({"fake:1": 10, "fake:2": 10, "fake:3": 10}, fail_set={"fake:2"})
    changes: list[int] = []
    cache = BrightnessCache(backend, on_change=lambda: changes.append(1))
    cache.poll_once()
    changes.clear()

    with pytest.raises(BrightnessError, match="fake:2"):
        cache.change("all", "set", 60)

    assert_that([backend.levels[i] for i in ("fake:1", "fake:2", "fake:3")]).is_equal_to([60, 10, 60])
    assert_that(cache.level("fake:1")).is_equal_to(60)
    assert_that(cache.level("fake:2")).is_equal_to(10)
    assert_that(changes).is_length(1)


def test_cache_single_monitor_vanishing_between_list_and_set_is_a_clear_error() -> None:
    backend = FakeBackend({"fake:1": 10})
    cache = BrightnessCache(backend)
    cache.poll_once()
    backend.vanished.add("fake:1")

    with pytest.raises(BrightnessError, match="fake:1"):
        cache.change("fake:1", "set", 50)


def test_cache_unknown_monitor_id_errors() -> None:
    cache = BrightnessCache(FakeBackend({"fake:1": 10}))
    cache.poll_once()

    with pytest.raises(BrightnessError, match="fake:9"):
        cache.change("fake:9", "set", 50)


def test_cache_poll_picks_up_external_change_and_notifies_only_on_change() -> None:
    backend = FakeBackend({"fake:1": 10, "fake:2": 30})
    changes: list[int] = []
    cache = BrightnessCache(backend, on_change=lambda: changes.append(1))

    cache.poll_once()
    assert_that(changes).is_length(1)
    cache.poll_once()
    assert_that(changes).is_length(1)

    backend.levels["fake:1"] = 50
    cache.poll_once()
    assert_that(changes).is_length(2)
    assert_that(cache.level("fake:1")).is_equal_to(50)
    assert_that(cache.average()).is_equal_to(40)
    assert_that([m.id for m in cache.monitors()]).is_equal_to(["fake:1", "fake:2"])


def test_cache_poll_notices_a_vanished_monitor() -> None:
    backend = FakeBackend({"fake:1": 10, "fake:2": 30})
    changes: list[int] = []
    cache = BrightnessCache(backend, on_change=lambda: changes.append(1))
    cache.poll_once()
    backend.vanished.add("fake:2")
    cache.poll_once()

    assert_that(len(changes)).is_equal_to(2)
    assert_that([m.id for m in cache.monitors()]).is_equal_to(["fake:1"])
    assert_that(cache.level("fake:2")).is_none()


def test_cache_on_change_runs_outside_the_lock() -> None:
    backend = FakeBackend({"fake:1": 10})
    seen: list[int | None] = []
    cache: BrightnessCache

    def reenter() -> None:
        seen.append(cache.level("fake:1"))  # deadlocks if the lock were held

    cache = BrightnessCache(backend, on_change=reenter)
    done = threading.Thread(target=cache.poll_once)
    done.start()
    done.join(timeout=2)

    assert_that(done.is_alive()).is_false()
    assert_that(seen).is_equal_to([10])


def test_cache_thread_polls_and_stop_joins() -> None:
    backend = FakeBackend({"fake:1": 10})
    polled = threading.Event()
    cache = BrightnessCache(backend, interval=0.01, on_change=polled.set)

    cache.start()
    cache.start()
    assert_that(polled.wait(2)).is_true()
    backend.levels["fake:1"] = 77
    polled.clear()
    assert_that(polled.wait(2)).is_true()
    cache.stop()

    assert_that(cache.level("fake:1")).is_equal_to(77)
    assert_that([t for t in threading.enumerate() if t.name == "brightness-poll"]).is_empty()
    cache.stop()


# --- default D-Bus sender: error replies must not read as success


class _DBusErrorResponse(Exception):
    pass


def _fake_jeepney(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    """Install a jeepney whose connection answers with ``reply``; unwrap_msg raises on an error reply, like jeepney."""
    events: list[str] = []

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

    jeepney = ModuleType("jeepney")
    jeepney.DBusAddress = lambda *a, **k: ("addr", a, k)  # type: ignore[attr-defined]
    jeepney.new_method_call = lambda *a, **k: ("call", a)  # type: ignore[attr-defined]
    jeepney.unwrap_msg = unwrap_msg  # type: ignore[attr-defined]
    io = ModuleType("jeepney.io")
    blocking = ModuleType("jeepney.io.blocking")
    blocking.open_dbus_connection = lambda bus="SESSION": Connection()  # type: ignore[attr-defined]
    for name, module in {"jeepney": jeepney, "jeepney.io": io, "jeepney.io.blocking": blocking}.items():
        monkeypatch.setitem(sys.modules, name, module)
    return events


def test_default_sender_error_reply_is_a_brightness_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sysfs(tmp_path, "bl", 10, 100)
    events = _fake_jeepney(monkeypatch, "error-reply")

    with pytest.raises(BrightnessError, match="backlight:bl"):
        LogindBacklight(tmp_path).set("backlight:bl", 50)
    assert_that(events).is_equal_to(["sent", "closed"])


def test_default_sender_ok_reply_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sysfs(tmp_path, "bl", 10, 100)
    _fake_jeepney(monkeypatch, "ok-reply")

    LogindBacklight(tmp_path).set("backlight:bl", 50)


def test_refused_logind_write_leaves_cache_untouched_and_does_not_notify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sysfs(tmp_path, "bl", 10, 100)
    _fake_jeepney(monkeypatch, "error-reply")
    changes: list[int] = []
    cache = BrightnessCache(LogindBacklight(tmp_path), on_change=lambda: changes.append(1))
    cache.poll_once()
    changes.clear()

    with pytest.raises(BrightnessError):
        cache.change("backlight:bl", "set", 80)

    assert_that(cache.level("backlight:bl")).is_equal_to(10)
    assert_that(changes).is_empty()


# --- start/stop from different threads ---


def test_a_stop_during_start_waits_for_the_thread_to_be_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    real_thread = threading.Thread
    published, errors = threading.Event(), []

    class SlowStart(real_thread):  # type: ignore[misc, valid-type]
        def start(self) -> None:
            if self.name == "brightness-poll":
                published.set()
                time.sleep(0.3)  # a window in which stop() could see the thread before it was started
            super().start()

    class _Empty:
        def list_monitors(self) -> list[Monitor]:
            return []

    cache = BrightnessCache(_Empty(), interval=0.05)

    def stopper() -> None:
        assert published.wait(5)
        try:
            cache.stop()
        except RuntimeError as exc:
            errors.append(exc)

    stopping = real_thread(target=stopper)
    stopping.start()
    monkeypatch.setattr(threading, "Thread", SlowStart)
    cache.start()
    monkeypatch.undo()
    stopping.join(5)

    assert_that(errors).is_empty()
    assert_that([t for t in threading.enumerate() if t.name == "brightness-poll" and t.is_alive()]).is_empty()
