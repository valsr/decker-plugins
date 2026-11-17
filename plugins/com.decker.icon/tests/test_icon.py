"""Tests for the Icon plugin (com.decker.icon), run through the SDK loop on pipes."""

import importlib.util
import json
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.common.version import is_compatible
from decker.plugin.icons import resolve_icon
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import apply_schema
from decker_plugin_sdk import run

_DIR = Path(__file__).parents[1]
_ACTION = "com.decker.icon.icon"
_MANIFEST = PluginManifest.load(_DIR / "manifest.json")
_SCHEMA = _MANIFEST.actions[0].settings
_REF = "pack:com.decker.fontawesome.solid/house.svg"


@pytest.fixture(scope="module", name="plugin")
def plugin_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_icon", _DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(**icon: Any) -> dict[str, Any]:
    return apply_schema(_SCHEMA, {"icon": icon} if icon else {})


class Harness:
    """Runs the plugin through the SDK loop on os.pipe streams."""

    def __init__(self, plugin: ModuleType) -> None:
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        self._thread = threading.Thread(
            target=run, args=({_ACTION: plugin.IconAction}, self._plugin_in, self._plugin_out)
        )
        self._thread.start()
        self.send("hello", payload={"protocol": 1, "decker_version": "x", "plugin_id": "com.decker.icon"})
        assert_that(self.recv()["event"]).is_equal_to("ready")

    def send(self, event: str, context: str | None = None, payload: dict | None = None) -> None:
        data: dict[str, Any] = {"event": event, "payload": payload or {}}
        if context:
            data["context"] = context
        self._to_plugin.write(json.dumps(data).encode() + b"\n")
        self._to_plugin.flush()

    def recv(self) -> dict:
        line = self._from_plugin.readline()
        assert line, "plugin closed stdout"
        return json.loads(line)

    def recv_until(self, event: str) -> dict:
        while True:
            message = self.recv()
            if message["event"] == event:
                return message

    def appear(self, settings: dict[str, Any]) -> None:
        self.send(
            "will_appear",
            "c1",
            {
                "action": _ACTION,
                "device": "d",
                "key": {"index": 0, "column": 0, "row": 0},
                "settings": settings,
                "state": 0,
            },
        )

    def close(self) -> None:
        self.send("shutdown")
        self._thread.join(5)
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()


@pytest.fixture(name="harness")
def harness_fixture(plugin: ModuleType):
    harness = Harness(plugin)
    yield harness
    harness.close()


def test_manifest_is_valid_and_gated_on_0_3() -> None:
    assert_that(_MANIFEST.id).is_equal_to("com.decker.icon")
    assert_that(_MANIFEST.name).is_equal_to("Icon")
    assert_that(_MANIFEST.version).is_equal_to("1.0.0")
    assert_that(_MANIFEST.decker).is_equal_to(">=0.3")
    assert_that(is_compatible(_MANIFEST.decker, "0.2.0")).is_false()
    assert_that(is_compatible(_MANIFEST.decker, "0.3.0")).is_true()
    assert_that(is_compatible(">=0.2", "0.3.0")).is_true()  # older plugins keep installing


def test_manifest_declares_one_icon_action() -> None:
    (spec,) = _MANIFEST.actions
    assert_that(spec.id).is_equal_to(_ACTION)
    assert_that([f.key for f in spec.settings if hasattr(f, "type")]).is_equal_to(["icon"])
    assert_that(spec.settings[0].type).is_equal_to("icon")
    assert_that(resolve_icon(_DIR, _MANIFEST.icon)).is_not_none()
    assert_that(resolve_icon(_DIR, spec.icon)).is_not_none()
    assert_that(_MANIFEST.runtime).is_not_none()
    assert_that(_MANIFEST.runtime.requirements).is_empty()  # type: ignore[union-attr]


def test_default_settings_show_nothing(harness: Harness) -> None:
    harness.appear(_settings())

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to({"image": None})


def test_will_appear_with_icon_sends_set_image_icon_and_colour(harness: Harness) -> None:
    harness.appear(_settings(ref=_REF, color="#ff0000"))

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to({"icon": _REF, "color": "#ff0000"})


def test_default_colour_is_white(harness: Harness) -> None:
    harness.appear(_settings(ref=_REF))

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to({"icon": _REF, "color": "#ffffff"})


def test_settings_changed_updates_the_icon(harness: Harness) -> None:
    harness.appear(_settings(ref=_REF, color="#ff0000"))
    harness.recv_until("set_image")

    harness.send("settings_changed", "c1", {"settings": _settings(ref="pack:p/other.svg", color="#00ff0080")})

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to(
        {"icon": "pack:p/other.svg", "color": "#00ff0080"}
    )


def test_clearing_the_ref_clears_the_image(harness: Harness) -> None:
    harness.appear(_settings(ref=_REF))
    harness.recv_until("set_image")

    harness.send("settings_changed", "c1", {"settings": _settings(ref="")})

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to({"image": None})


def test_hand_edited_garbage_settings_do_not_crash(plugin: ModuleType, harness: Harness) -> None:
    harness.appear({"icon": "not an object"})

    assert_that(harness.recv_until("set_image")["payload"]).is_equal_to({"image": None})
