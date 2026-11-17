"""Shared test harness: runs the Profiles plugin through the SDK loop on pipes."""

import importlib.util
import json
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from assertpy import assert_that
from decker_plugin_sdk import run

PLUGIN_DIR = Path(__file__).parents[1]
CONTEXT = "c1"


def load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_profiles", PLUGIN_DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Harness:
    """One action class on os.pipe streams."""

    def __init__(self, plugin: ModuleType, action_id: str, class_name: str) -> None:
        self.action_id = action_id
        self._line = b""
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        self._thread = threading.Thread(
            target=run, args=({action_id: getattr(plugin, class_name)}, self._plugin_in, self._plugin_out)
        )
        self._thread.start()
        self.send("hello", payload={"protocol": 1, "decker_version": "x", "plugin_id": "com.decker.profiles"})
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

    def collect_settled(self) -> list[dict]:
        """Every message the plugin sent for earlier events.

        Events of one key are handled in order on a queue, so a final settings change that makes a Go To key
        send a recognisable title is a barrier: once it arrives, nothing earlier is still on its way.
        """
        self.change({"profile": {"profile_id": 99, "name": "SENTINEL", "index": 1, "icon": "decker:logo"}})
        seen: list[dict] = []
        while True:
            message = self.recv()
            if message["event"] == "set_title" and message["payload"]["title"] == "SENTINEL":
                return seen
            seen.append(message)

    def appear(self, settings: dict[str, Any]) -> None:
        self.send(
            "will_appear",
            CONTEXT,
            {
                "action": self.action_id,
                "device": "d",
                "key": {"index": 0, "column": 0, "row": 0},
                "settings": settings,
                "state": 0,
            },
        )

    def change(self, settings: dict[str, Any]) -> None:
        self.send("settings_changed", CONTEXT, {"settings": settings})

    def press(self) -> None:
        self.send("press", CONTEXT)

    def close(self) -> None:
        self.send("shutdown")
        self._thread.join(5)
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()
