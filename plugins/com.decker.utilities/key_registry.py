"""The registry shared by the Timer and Stopwatch cards: per-key state, live keys, serialised paints, one ticker.

Lock order is always the key's paint lock, then the registry lock. A subclass supplies the state object of a key
(``_prepare``), what to read from it for a paint (``_snapshot``), how to draw that (``_draw``) and the ``tick``.
"""

import threading
from dataclasses import dataclass, field
from typing import Any

from decker_plugin_sdk import CardContext
from ticker import Ticker


@dataclass
class Face:
    """A live key; the lock serialises its paints so the last one shows the newest state."""

    ctx: CardContext
    lock: threading.Lock = field(default_factory=threading.Lock)


class KeyRegistry[T]:
    """State objects keyed by context id, the live keys, and the ticker that drives ``tick``."""

    def __init__(self, interval: float, ticker_name: str) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, T] = {}
        self._faces: dict[str, Face] = {}
        self._ticker = Ticker(interval, self.tick, ticker_name)

    # --- hooks

    def _prepare(self, ctx: CardContext) -> None:
        """A key appeared or changed: make or adjust its state. Called with the lock held."""
        raise NotImplementedError

    def _snapshot(self, ctx: CardContext) -> Any:
        """What a paint needs from the key's state. Called with the lock held."""
        raise NotImplementedError

    def _draw(self, img: Any, settings: dict[str, Any], snapshot: Any) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        raise NotImplementedError

    # --- registry and keys

    def tracked(self, context: str) -> bool:
        with self._lock:
            return context in self._faces

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._faces.clear()

    def track(self, ctx: CardContext, paint: bool = True) -> Face:
        """A key appeared or its settings changed: prepare its state, remember the key, repaint."""
        with self._lock:
            self._prepare(ctx)
            face = self._faces.get(ctx.context)
            if face is None:
                face = self._faces[ctx.context] = Face(ctx)
            face.ctx = ctx
        if paint:
            self.paint(face)
        return face

    def untrack(self, ctx: CardContext) -> None:
        with self._lock:
            self._faces.pop(ctx.context, None)

    def paint(self, face: Face) -> None:
        """Draw the key; the state is read inside the key's lock so the newest paint shows the newest state."""
        with face.lock:
            settings = face.ctx.settings
            with self._lock:
                snapshot = self._snapshot(face.ctx)
            with face.ctx.canvas.paint() as img:
                img.paste((0, 0, 0, 0), (0, 0, *img.size))
                self._draw(img, settings, snapshot)

    def _paint_key(self, context: str) -> None:
        with self._lock:
            face = self._faces.get(context)
        if face is not None:
            self.paint(face)

    # --- ticker

    def start_ticker(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def ticker_alive(self) -> bool:
        return self._ticker.alive()
