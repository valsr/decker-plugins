"""Display brightness: the global action, the Level card and the brightness variables.

One ``BrightnessCache`` (its own poll thread) holds the last known levels. The action runs on an SDK pool worker,
so it may block on the hardware; the card faces and the variable getters only read the cache. Every change of the
cache re-signals the variables, registers or withdraws the per-monitor ones and redraws the live Level cards.

A Level card's ``monitor`` setting also steers its own bindings: when a binding says "all monitors" (the default)
the card's monitor is used, so one setting picks both the monitor shown and the monitor changed.
"""

import asyncio
import logging
import threading
from typing import Any

from brightness import Backend, BrightnessCache, BrightnessError, default_backend, label_monitors
from decker_plugin_sdk import (
    ActionCallContext,
    ActionError,
    CardContext,
    DeckerPlugin,
    PluginContext,
    action,
    card,
    main,
    options,
    register_variable,
    signal_variable_updated,
    unregister_variable,
    variable,
)
from drawing import level_grey

_log = logging.getLogger(__name__)

ACTION = "com.decker.utilities.brightness"
LEVEL_CARD = "com.decker.utilities.brightness-level"
_MODES = ("increase", "decrease", "set")
_ALL = "all"
_ICON = "fas:sun"
_UNKNOWN_TINT = "#808080"
_NO_LEVEL = "—"
_LEVEL_VARIABLE = "brightness_level"
_MONITOR_VARIABLE = "brightness_level_{}"
_POLL_SECONDS = 5.0


class _Service:
    """The backend, its cache, the live Level cards and the pattern variables currently registered."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._backend: Backend | None = None
        self._cache: BrightnessCache | None = None
        self._cards: dict[str, CardContext] = {}
        self._registered: set[str] = set()

    def set_backend(self, backend: Backend | None) -> None:
        with self._lock:
            cache, self._cache = self._cache, None
            self._backend = backend
            self._cards.clear()
            self._registered.clear()
        if cache is not None:
            cache.stop()

    def cache(self) -> BrightnessCache:
        with self._lock:
            if self._cache is None:
                self._cache = BrightnessCache(self._backend or default_backend(), _POLL_SECONDS, self._changed)
            return self._cache

    def track(self, ctx: CardContext) -> None:
        with self._lock:
            self._cards[ctx.context] = ctx

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._cards.pop(ctx.context, None)

    def begin_run(self) -> BrightnessCache:
        """Start polling for a new SDK runtime; its variables and cards are not known to the server yet."""
        with self._lock:
            self._registered.clear()
        cache = self.cache()
        cache.start()
        return cache

    def _changed(self) -> None:
        self._sync_variables()
        with self._lock:
            cards = list(self._cards.values())
        for ctx in cards:
            show_level(ctx)

    def _sync_variables(self) -> None:
        with self._sync_lock:
            wanted = {_MONITOR_VARIABLE.format(i) for i in range(1, len(self.cache().monitors()) + 1)}
            with self._lock:
                gone, new = self._registered - wanted, wanted - self._registered
                self._registered = wanted
            try:
                for name in sorted(gone):
                    unregister_variable(name)
                for name in sorted(new):
                    register_variable(name)
                for name in (_LEVEL_VARIABLE, *sorted(wanted)):
                    signal_variable_updated(name)
            except RuntimeError:  # no plugin runtime is running (shutdown, or a test without one)
                _log.debug("brightness variables not signalled: no runtime")


_service = _Service()


def set_backend_for_tests(backend: Backend | None) -> None:
    """Use ``backend`` for the next cache (None: the platform default again); stops the current cache."""
    _service.set_backend(backend)


def cache() -> BrightnessCache:
    """The plugin's brightness cache."""
    return _service.cache()


@main(interval=None)
async def _poll_until_shutdown(ctx: PluginContext) -> None:
    started = None
    try:
        started = _service.begin_run()
        await asyncio.Event().wait()
    finally:
        if started is not None:
            started.stop()


@options("monitors")
def monitor_options() -> list[dict[str, str]]:
    """The option "All monitors", then each monitor under its (de-duplicated) name."""
    current = cache()
    if not current.monitors():
        current.poll_once()
    labelled = label_monitors(current.monitors())
    return [{"label": "All monitors", "value": _ALL}, *({"label": label, "value": mid} for mid, label in labelled)]


def _int_value(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ActionError(f"value must be a whole number, not {raw!r}")
    return max(0, min(100, raw))


def _chosen_monitor(ctx: ActionCallContext) -> str:
    monitor = ctx.args.get("monitor", _ALL)
    if not isinstance(monitor, str) or not monitor:
        raise ActionError(f"monitor must be a monitor id or 'all', not {monitor!r}")
    own = ctx.card is not None and isinstance(getattr(ctx.card, "instance", None), BrightnessLevelCard)
    if monitor == _ALL and own:
        chosen = ctx.card.settings.get("monitor")
        if isinstance(chosen, str) and chosen:
            return chosen
    return monitor


@action(ACTION)
def brightness(ctx: ActionCallContext) -> int:
    """Raise, lower or set display brightness; returns the new level (the first changed monitor's)."""
    mode = ctx.args.get("mode", "increase")
    if mode not in _MODES:
        raise ActionError(f"unknown mode {mode!r}")
    value = _int_value(ctx.args.get("value", 10))
    monitor = _chosen_monitor(ctx)
    current = cache()
    if not current.monitors():
        current.poll_once()
    known = {m.id for m in current.monitors()}
    if not known:
        raise ActionError("no monitor found")
    if monitor != _ALL and monitor not in known:
        raise ActionError("monitor not available")
    try:
        applied = current.change(monitor, mode, value)
    except BrightnessError as exc:
        raise ActionError(str(exc)) from exc
    return next(iter(applied.values()))


def _level_for(monitor: Any) -> int | None:
    current = cache()
    if not isinstance(monitor, str) or monitor == _ALL or not monitor:
        return current.average()
    return current.level(monitor)


def show_level(ctx: CardContext) -> None:
    """Draw the Level card: the sun tinted by the level, and the level as the title (a dash when unknown)."""
    level = _level_for(ctx.settings.get("monitor", _ALL))
    ctx.set_icon(_ICON, _UNKNOWN_TINT if level is None else level_grey(level))
    ctx.set_title(_NO_LEVEL if level is None else f"{level}%")


@card(LEVEL_CARD)
class BrightnessLevelCard(DeckerPlugin):
    """The sun, tinted by the chosen monitor's brightness (average for all), with the level as its title."""

    def on_will_appear(self, ctx: CardContext) -> None:
        _service.track(ctx)
        show_level(ctx)

    def on_will_disappear(self, ctx: CardContext) -> None:
        _service.untrack(ctx)

    def on_settings_changed(self, ctx: CardContext) -> None:
        show_level(ctx)


@variable(_LEVEL_VARIABLE)
def _first_monitor_level() -> str:
    monitors = cache().monitors()
    level = cache().level(monitors[0].id) if monitors else None
    return "" if level is None else str(level)


@variable("brightness_level_{monitor}")
def _monitor_level(monitor: str) -> str | None:
    monitors = cache().monitors()
    index = int(monitor) if monitor.isdigit() else 0
    if not 1 <= index <= len(monitors):
        return None
    level = cache().level(monitors[index - 1].id)
    return "" if level is None else str(level)
