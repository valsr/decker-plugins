"""Shared test harness: runs one Utilities card class and the plugin's actions through the SDK loop on pipes."""

import importlib.util
import json
import os
import sys
import threading
from collections import deque
from pathlib import Path
from types import ModuleType
from typing import Any

from assertpy import assert_that
from decker_plugin_sdk import run
from decker_plugin_sdk._actions import registered_actions

PLUGIN_DIR = Path(__file__).parents[1]
PLUGIN_ID = "com.decker.utilities"
CONTEXT = "c1"
DEVICE = "dev1"  # the device of the appeared card and the default device of run_action
PROTOCOL = 5
_KEY = {"index": 0, "column": 0, "row": 0}


def load_plugin() -> ModuleType:
    """Import plugin.py the way Decker runs it: with the plugin directory on sys.path for its sibling modules."""
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location("decker_plugin_test_utilities", PLUGIN_DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Harness:
    """One card class plus every Utilities action, served on os.pipe streams (protocol 5)."""

    def __init__(self, plugin: ModuleType, card_id: str, class_name: str) -> None:
        self.card_id = card_id
        self.seen: list[str] = []  # event names of every message received so far, in order
        self.sent: list[dict] = []  # messages that arrived between the last run_action's request and its result
        self._backlog: deque[dict] = deque()  # received during run_action, not yet consumed by recv
        self._settings: dict[str, Any] = {}
        self._requests = 0
        self.deck_levels: dict[str, int] = {DEVICE: 50}  # answers to get_deck_brightness; a missing device is an error
        self.deck_gets: list[str] = []  # devices of every get_deck_brightness received
        self.deck_sets: list[dict] = []  # payload of every set_deck_brightness received
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        actions = {k: v for k, v in registered_actions().items() if k.startswith(f"{PLUGIN_ID}.")}
        self._thread = threading.Thread(
            target=run, args=({card_id: getattr(plugin, class_name)}, self._plugin_in, self._plugin_out, actions)
        )
        self._thread.start()
        self.send_event(
            "hello",
            {"protocol": PROTOCOL, "decker_version": "x", "plugin_id": PLUGIN_ID, "global_settings": {}},
        )
        assert_that(self.recv()["event"]).is_equal_to("ready")

    def send_event(self, event: str, payload: dict | None = None, context: str | None = None) -> None:
        """Send any server-to-plugin event; `context` is the key context, omitted for plugin-wide events."""
        data: dict[str, Any] = {"event": event, "payload": payload or {}}
        if context:
            data["context"] = context
        self._to_plugin.write(json.dumps(data).encode() + b"\n")
        self._to_plugin.flush()

    def recv(self) -> dict:
        """The next message from the plugin; fails after 5 s of silence."""
        if self._backlog:
            message = self._backlog.popleft()
        else:
            message = self._read()
        self.seen.append(message["event"])
        return message

    def connect(self, device: str) -> None:
        """Tell the plugin a deck connected."""
        self.send_event("device_connected", {"device": device})

    def disconnect(self, device: str) -> None:
        """Tell the plugin a deck went away."""
        self.send_event("device_disconnected", {"device": device})

    def _read(self) -> dict:
        message = self._read_raw()
        self._serve_deck(message)
        return message

    def _serve_deck(self, message: dict) -> None:
        """Play the server for deck brightness: answer gets from `deck_levels`, record gets and sets."""
        payload = message.get("payload") or {}
        if message["event"] == "set_deck_brightness":
            self.deck_sets.append(payload)
        elif message["event"] == "get_deck_brightness":
            device = payload["device"]
            self.deck_gets.append(device)
            if device in self.deck_levels:
                reply = {"request": payload["request"], "device": device, "percent": self.deck_levels[device]}
            else:
                reply = {"request": payload["request"], "error": f"unknown device {device}"}
            self.send_event("deck_brightness", reply)

    def _read_raw(self) -> dict:
        line: list[bytes] = []
        reader = threading.Thread(target=lambda: line.append(self._from_plugin.readline()), daemon=True)
        reader.start()
        reader.join(5)
        assert not reader.is_alive(), "timed out waiting for the plugin"
        assert line[0], "plugin closed stdout"
        return json.loads(line[0])

    def recv_until(self, event: str) -> dict:
        """Skip messages until one of `event` arrives and return it."""
        while True:
            message = self.recv()
            if message["event"] == event:
                return message

    def appear(
        self, settings: dict[str, Any], bindings: dict[str, Any] | None = None, size: tuple[int, int] = (144, 144)
    ) -> None:
        """Show the card on key 0 with these (already schema-applied) settings."""
        self._settings = settings
        self.send_event(
            "will_appear",
            {
                "card": self.card_id,
                "device": DEVICE,
                "key": _KEY,
                "size": list(size),
                "settings": settings,
                "bindings": bindings or {},
                "state": 0,
            },
            CONTEXT,
        )

    def change(self, settings: dict[str, Any], bindings: dict[str, Any] | None = None) -> None:
        """Change the card's settings; later run_action calls carry them on the card."""
        self._settings = settings
        self.send_event("settings_changed", {"settings": settings, "bindings": bindings or {}}, CONTEXT)

    def run_action(self, action_id: str, args: dict[str, Any], with_card: bool = True, device: str = DEVICE) -> dict:
        """Run an action (with this key as the card unless `with_card` is false); return its action_result payload.

        The call carries `device` either way, so a context-less call can be device-scoped. Messages the plugin
        sent earlier are first read into the backlog (a ping/pong barrier), so `sent` holds what arrived between
        this request and its result; events of the card's own key still in flight may be late and land in it.
        Everything in `sent` is still delivered to later `recv`/`recv_until` calls.
        """
        self._settle()
        self._requests += 1
        card = {
            "context": CONTEXT,
            "card": self.card_id,
            "plugin": PLUGIN_ID,
            "device": device,
            "key": _KEY,
            "size": [144, 144],
            "settings": self._settings,
            "last_paint": None,
        }
        self.send_event(
            "run_action",
            {
                "action": action_id,
                "request": f"r{self._requests}",
                "args": args,
                "device": device,
                "input": "press" if with_card else "plugin",
                "called_at": "2026-11-21T10:00:00.123+00:00",
                "card": card if with_card else None,
                "caller": None,
                "chain": "ch",
                "depth": 0,
            },
        )
        self.sent = []
        while True:
            message = self._read()
            if message["event"] == "action_result":
                self.seen.append("action_result")
                return message["payload"]
            self.sent.append(message)
            self._backlog.append(message)

    def _settle(self) -> None:
        """Move everything the plugin has already sent into the backlog, up to the answer to a ping."""
        self.send_event("ping")
        while True:
            message = self._read()
            if message["event"] == "pong":
                return
            self._backlog.append(message)

    def sent_payloads(self, event: str) -> list[dict]:
        """Payloads (minus the request id) of `event` messages sent before the last action_result."""
        return [{k: v for k, v in m["payload"].items() if k != "request"} for m in self.sent if m["event"] == event]

    def close(self) -> None:
        self.send_event("shutdown")
        self._thread.join(5)
        assert not self._thread.is_alive(), "the plugin thread did not stop after shutdown"
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()
