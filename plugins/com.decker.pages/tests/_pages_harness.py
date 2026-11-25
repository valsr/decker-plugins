"""Shared test harness: runs the Pages plugin through the SDK loop on pipes."""

import importlib.util
import json
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from assertpy import assert_that
from decker_plugin_sdk import run
from decker_plugin_sdk._actions import registered_actions

PLUGIN_DIR = Path(__file__).parents[1]
CONTEXT = "c1"


def load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_pages", PLUGIN_DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Harness:
    """The plugin's actions on os.pipe streams, run as if from a card."""

    def __init__(self, plugin: ModuleType, action_id: str) -> None:
        self.action_id = action_id
        self._requests = 0
        self.sent: list[dict] = []
        self._line = b""
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        self._thread = threading.Thread(
            target=run,
            args=(
                {},
                self._plugin_in,
                self._plugin_out,
                {k: v for k, v in registered_actions().items() if k.startswith("com.decker.pages.")},
            ),
        )
        self._thread.start()
        self.send(
            "hello",
            payload={"protocol": 4, "decker_version": "x", "plugin_id": "com.decker.pages", "global_settings": {}},
        )
        assert_that(self.recv()["event"]).is_equal_to("ready")

    def send(self, event: str, context: str | None = None, payload: dict | None = None) -> None:
        data: dict[str, Any] = {"event": event, "payload": payload or {}}
        if context:
            data["context"] = context
        self._to_plugin.write(json.dumps(data).encode() + b"\n")
        self._to_plugin.flush()

    def recv(self) -> dict:
        reader = threading.Thread(target=self._read_line, daemon=True)
        self._line = b""
        reader.start()
        reader.join(5)
        assert not reader.is_alive(), "timed out waiting for the plugin"
        assert self._line, "plugin closed stdout"
        return json.loads(self._line)

    def _read_line(self) -> None:
        self._line = self._from_plugin.readline()

    def recv_until(self, event: str) -> dict:
        while True:
            message = self.recv()
            if message["event"] == event:
                return message

    def run_action(self, action_id: str, args: dict[str, Any], with_card: bool = True) -> dict:
        """Send run_action (with this key as the card) and return its action_result payload."""
        self._requests += 1
        card = {
            "context": CONTEXT,
            "card": self.action_id,
            "plugin": "com.decker.pages",
            "device": "d",
            "key": {"index": 0, "column": 0, "row": 0},
            "size": [72, 72],
            "settings": {},
            "last_paint": None,
        }
        self.send(
            "run_action",
            payload={
                "action": action_id,
                "request": f"r{self._requests}",
                "args": args,
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
            message = self.recv()
            if message["event"] == "action_result":
                return message["payload"]
            self.sent.append(message)

    def sent_payloads(self, event: str) -> list[dict]:
        """Payloads (minus the request id) of `event` messages sent before the last action_result."""
        return [{k: v for k, v in m["payload"].items() if k != "request"} for m in self.sent if m["event"] == event]

    def close(self) -> None:
        self.send("shutdown")
        self._thread.join(5)
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()
