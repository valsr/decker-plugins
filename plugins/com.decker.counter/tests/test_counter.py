"""Tests for the Counter plugin (com.decker.counter), run through the SDK loop on pipes."""

import base64
import importlib.util
import io
import json
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import apply_schema
from decker.server.fonts import BUNDLED_FONT_DIR
from decker_plugin_sdk import run
from PIL import Image, ImageFont

_DIR = Path(__file__).parents[1]
_ACTION = "com.decker.counter.counter"
_SCHEMA = PluginManifest.load(_DIR / "manifest.json").actions[0].settings


@pytest.fixture(scope="module", name="counter")
def counter_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_counter", _DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(**values: Any) -> dict[str, Any]:
    return apply_schema(_SCHEMA, values)


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


class Harness:
    """Runs the counter through the SDK loop on os.pipe streams."""

    def __init__(self, counter: ModuleType) -> None:
        self.seen: list[str] = []
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        self._thread = threading.Thread(
            target=run, args=({_ACTION: counter.CounterAction}, self._plugin_in, self._plugin_out)
        )
        self._thread.start()
        self.send("hello", payload={"protocol": 1, "decker_version": "x", "plugin_id": "com.decker.counter"})
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
        message = json.loads(line)
        self.seen.append(message["event"])
        return message

    def recv_until(self, event: str) -> dict:
        while True:
            message = self.recv()
            if message["event"] == event:
                return message

    def appear(self, **values: Any) -> None:
        self.send(
            "will_appear",
            "c1",
            {
                "action": _ACTION,
                "device": "d",
                "key": {"index": 0, "column": 0, "row": 0},
                "settings": _settings(**values),
                "state": 0,
            },
        )

    def next_png(self) -> bytes:
        return base64.b64decode(self.recv_until("set_image")["payload"]["image"])

    def close(self) -> None:
        self.send("shutdown")
        self._thread.join(5)
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()


@pytest.fixture(name="harness")
def harness_fixture(counter):
    harness = Harness(counter)
    yield harness
    harness.close()


class TestGestures:
    def test_double_press_registered_only_with_double_step(self, harness):
        harness.appear()
        without = harness.recv_until("set_gestures")["payload"]["gestures"]
        harness.send("settings_changed", "c1", {"settings": _settings(double_step=5)})
        with_double = harness.recv_until("set_gestures")["payload"]["gestures"]

        assert_that(without).is_equal_to(["long_press", "press"])
        assert_that(with_double).is_equal_to(["double_press", "long_press", "press"])

    def test_cleared_double_step_unregisters_it(self, harness):
        harness.appear(double_step=5)
        harness.recv_until("set_gestures")
        harness.send("settings_changed", "c1", {"settings": _settings(double_step=None)})

        assert_that(harness.recv_until("set_gestures")["payload"]["gestures"]).does_not_contain("double_press")


class TestCounting:
    def test_press_increments(self, harness, counter):
        harness.appear(step=3)
        assert_that(harness.next_png()).is_equal_to(counter.render(0))

        harness.send("press", "c1")
        assert_that(harness.next_png()).is_equal_to(counter.render(3))
        harness.send("press", "c1")
        assert_that(harness.next_png()).is_equal_to(counter.render(6))

    def test_default_step_is_one(self, harness, counter):
        harness.appear()
        harness.next_png()

        harness.send("press", "c1")

        assert_that(harness.next_png()).is_equal_to(counter.render(1))

    def test_double_press_adds_double_step(self, harness, counter):
        harness.appear(step=1, double_step=10)
        harness.next_png()

        harness.send("press", "c1")
        harness.next_png()
        harness.send("double_press", "c1")

        assert_that(harness.next_png()).is_equal_to(counter.render(11))

    def test_long_press_resets(self, harness, counter):
        harness.appear(step=4)
        harness.next_png()
        harness.send("press", "c1")
        harness.next_png()

        harness.send("long_press", "c1")

        assert_that(harness.next_png()).is_equal_to(counter.render(0))

    def test_max_wraps(self, harness, counter):
        harness.appear(step=2, max=4)
        harness.next_png()

        harness.send("press", "c1")
        assert_that(harness.next_png()).is_equal_to(counter.render(2))
        harness.send("press", "c1")
        assert_that(harness.next_png()).is_equal_to(counter.render(0))

    def test_counter_no_longer_sets_title(self, harness):
        harness.appear()
        harness.next_png()
        harness.send("press", "c1")
        harness.next_png()

        assert_that(harness.seen).does_not_contain("set_title")

    def test_settings_change_redraws(self, harness):
        harness.appear()
        harness.next_png()

        harness.send("settings_changed", "c1", {"settings": _settings(step=2)})

        assert_that(harness.next_png()).is_not_empty()


class TestSettingsSchema:
    def test_empty_double_step_becomes_none(self):
        assert_that(_settings(double_step="")["double_step"]).is_none()

    def test_defaults_match_the_original_counter(self):
        assert_that(_settings()).is_equal_to({"step": 1, "double_step": None, "max": 0})

    def test_appearance_keys_are_no_longer_settings(self):
        assert_that(_settings(background="#102030", title="Hi")).is_equal_to({"step": 1, "double_step": None, "max": 0})

    def test_manifest_declares_the_blue_background_default(self):
        spec = PluginManifest.load(_DIR / "manifest.json").actions[0]

        assert_that(spec.appearance).is_equal_to({"background": "#1f618d"})


class TestRender:
    def test_image_is_transparent_with_the_count(self, counter):
        image = Image.open(io.BytesIO(counter.render(8))).convert("RGBA")

        assert_that(image.size).is_equal_to((144, 144))
        assert_that(image.getpixel((2, 2))).is_equal_to((0, 0, 0, 0))
        assert_that(any(p[3] > 0 for p in image.get_flattened_data())).is_true()  # type: ignore[index]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_ink(data: bytes) -> bool:
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    return any(p[3] > 0 for p in image.get_flattened_data())  # type: ignore[index]


class TestFont:
    @pytest.fixture(name="recorder")
    def recorder_fixture(self, monkeypatch):
        used: list[str] = []
        real = ImageFont.truetype

        def _record(font: Any = None, *args: Any, **kwargs: Any) -> Any:
            if isinstance(font, str):  # load_default opens its built-in font from a BytesIO
                used.append(font)
            return real(font, *args, **kwargs)

        monkeypatch.setattr(ImageFont, "truetype", _record)
        return used

    def test_uses_the_bundled_dejavu_sans_bold(self, monkeypatch, recorder):
        monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED_FONT_DIR))
        module = _load("decker_plugin_test_counter_sdk")

        data = module.render(5)

        assert_that(recorder).is_equal_to([str(BUNDLED_FONT_DIR / "DejaVuSans-Bold.ttf")])
        assert_that(_has_ink(data)).is_true()

    def test_no_font_dir_falls_back_to_the_default_font(self, monkeypatch, recorder):
        monkeypatch.delenv("DECKER_FONT_DIR", raising=False)
        module = _load("decker_plugin_test_counter_nodir")

        data = module.render(5)

        assert_that(recorder).is_empty()
        assert_that(_has_ink(data)).is_true()

    def test_unopenable_font_file_falls_back(self, monkeypatch, tmp_path):
        broken = tmp_path / "DejaVuSans-Bold.ttf"
        broken.write_bytes(b"not a font")
        monkeypatch.setenv("DECKER_FONT_DIR", str(tmp_path))
        module = _load("decker_plugin_test_counter_broken")

        assert_that(_has_ink(module.render(5))).is_true()

    def test_missing_sdk_fonts_module_falls_back(self, monkeypatch, recorder):
        monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED_FONT_DIR))
        monkeypatch.setitem(sys.modules, "decker_plugin_sdk.fonts", None)  # makes the import raise ImportError
        module = _load("decker_plugin_test_counter_noimport")

        data = module.render(5)

        assert_that(recorder).is_empty()
        assert_that(_has_ink(data)).is_true()

    def test_plugin_no_longer_imports_subprocess(self, counter):
        assert_that(hasattr(counter, "subprocess")).is_false()
        assert_that((_DIR / "plugin.py").read_text()).does_not_contain("subprocess").does_not_contain("fc-match")
