"""Deck brightness: the global action, the Level card and the variables for the Stream Deck's own brightness.

Levels are only asked from the server when unknown; ``deck_brightness_changed`` keeps them current, and each change
repaints the Level cards of that deck and re-signals the variables.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from decker_plugin_sdk import (
    ActionCallContext,
    ActionError,
    CardContext,
    DeckerPlugin,
    action,
    card,
    connected_devices,
    get_deck_brightness,
    on_deck_brightness_changed,
    on_device_connected,
    on_device_disconnected,
    register_variable,
    set_deck_brightness,
    signal_variable_updated,
    unregister_variable,
    variable,
)
from drawing import level_grey

_log = logging.getLogger(__name__)

ACTION = "com.decker.utilities.deck-brightness"
LEVEL_CARD = "com.decker.utilities.deck-brightness-level"
_MODES = ("increase", "decrease", "set")
_ICON = "decker:logo"
_UNKNOWN_TINT = "#808080"
_NO_LEVEL = "—"
_LEVEL_VARIABLE = "deck_brightness_level"
_DEVICE_VARIABLE = "deck_brightness_level_{}"
_GET_TIMEOUT = 2.0


@dataclass
class _Face:
    """A live Level card; the lock serialises its paints so the last one shows the newest level."""

    ctx: CardContext
    lock: threading.Lock = field(default_factory=threading.Lock)


class _Decks:
    """The last known level of each deck and the live Level cards."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._levels: dict[str, int] = {}
        self._faces: dict[str, _Face] = {}

    def reset(self) -> None:
        with self._lock:
            self._levels.clear()
            self._faces.clear()

    def level(self, device: str) -> int | None:
        """The known level, asking the server once if there is none yet; None when it cannot say."""
        with self._lock:
            known = self._levels.get(device)
        if known is not None:
            return known
        try:
            fetched = get_deck_brightness(device, _GET_TIMEOUT)
        except (ActionError, RuntimeError) as exc:
            _log.debug("deck brightness of %s unknown: %s", device, exc)
            return None
        with self._lock:
            return self._levels.setdefault(device, fetched)  # a change that arrived meanwhile wins

    def set_level(self, device: str, percent: int) -> None:
        with self._lock:
            self._levels[device] = percent

    def forget(self, device: str) -> None:
        with self._lock:
            self._levels.pop(device, None)

    def track(self, ctx: CardContext) -> _Face:
        face = _Face(ctx)
        with self._lock:
            self._faces[ctx.context] = face
        return face

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._faces.pop(ctx.context, None)

    def faces_on(self, device: str) -> list[_Face]:
        with self._lock:
            return [f for f in self._faces.values() if f.ctx.device == device]


_decks = _Decks()


def reset_for_tests() -> None:
    """Forget every known level and card."""
    _decks.reset()


def _paint(face: _Face) -> None:
    with face.lock:
        level = _decks.level(face.ctx.device)
        face.ctx.set_icon(_ICON, _UNKNOWN_TINT if level is None else level_grey(level))
        face.ctx.set_title(_NO_LEVEL if level is None else f"{level}%")


def _signal(*names: str) -> None:
    try:
        for name in names:
            signal_variable_updated(name)
    except RuntimeError:  # no plugin runtime is running
        _log.debug("deck brightness variables not signalled: no runtime")


@on_deck_brightness_changed
def _brightness_changed(device: str, percent: int) -> None:
    _decks.set_level(device, percent)
    for face in _decks.faces_on(device):
        _paint(face)
    _signal(_LEVEL_VARIABLE, _DEVICE_VARIABLE.format(device))


@on_device_connected
def _device_connected(device: str) -> None:
    try:
        register_variable(_DEVICE_VARIABLE.format(device))
    except RuntimeError:
        _log.debug("deck brightness variable not registered: no runtime")
    _signal(_LEVEL_VARIABLE)


@on_device_disconnected
def _device_disconnected(device: str) -> None:
    _decks.forget(device)
    try:
        unregister_variable(_DEVICE_VARIABLE.format(device))
    except RuntimeError:
        _log.debug("deck brightness variable not unregistered: no runtime")
    _signal(_LEVEL_VARIABLE)


def _int_value(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ActionError(f"value must be a whole number, not {raw!r}")
    return max(0, min(100, raw))


def _device_of(ctx: ActionCallContext) -> str:
    device = ctx.card.device if ctx.card is not None else None
    device = device or ctx.device_id
    if not device:
        raise ActionError("no deck for this call")
    return device


@action(ACTION)
def deck_brightness(ctx: ActionCallContext) -> int:
    """Raise, lower or set the Stream Deck's brightness; returns the level sent (the server clamps it to 1-100)."""
    mode = ctx.args.get("mode", "increase")
    if mode not in _MODES:
        raise ActionError(f"unknown mode {mode!r}")
    value = _int_value(ctx.args.get("value", 10))
    device = _device_of(ctx)
    if mode == "set":
        target = value
    else:
        current = get_deck_brightness(device)
        target = max(0, min(100, current + value if mode == "increase" else current - value))
    set_deck_brightness(target, device)
    return target


@card(LEVEL_CARD)
class DeckBrightnessLevelCard(DeckerPlugin):
    """The Decker logo, tinted by the deck's brightness, with the level as its title."""

    def on_will_appear(self, ctx: CardContext) -> None:
        _paint(_decks.track(ctx))

    def on_will_disappear(self, ctx: CardContext) -> None:
        _decks.untrack(ctx)


@variable(_LEVEL_VARIABLE)
def _first_deck_level() -> str:
    devices = connected_devices()
    level = _decks.level(devices[0]) if devices else None
    return "" if level is None else str(level)


@variable("deck_brightness_level_{device}")
def _deck_level(device: str) -> str | None:
    if device not in connected_devices():
        return None
    level = _decks.level(device)
    return "" if level is None else str(level)
