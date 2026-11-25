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
from decker_plugin_sdk._actions import registered_actions
from PIL import Image, ImageFont

_DIR = Path(__file__).parents[1]
_CARD = "com.decker.counter.counter"
_MANIFEST = PluginManifest.load(_DIR / "manifest.json")
_CARD_SCHEMA = _MANIFEST.cards[0].settings
_ACTIONS = {spec.id: spec for spec in _MANIFEST.actions}
_INC = "com.decker.counter.increment"
_DEC = "com.decker.counter.decrement"
_RESET = "com.decker.counter.reset"
_SIZE = 144


@pytest.fixture(scope="module", name="counter")
def counter_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_counter", _DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _card_settings(**values: Any) -> dict[str, Any]:
    return apply_schema(_CARD_SCHEMA, values)


def _args(action_id: str, **values: Any) -> dict[str, Any]:
    return apply_schema(_ACTIONS[action_id].settings, values)


class Harness:
    """Runs the counter through the SDK loop on os.pipe streams."""

    def __init__(self, counter: ModuleType) -> None:
        self.seen: list[str] = []
        self._requests = 0
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        actions = {k: v for k, v in registered_actions().items() if k in _ACTIONS}
        self._thread = threading.Thread(
            target=run, args=({_CARD: counter.CounterCard}, self._plugin_in, self._plugin_out, actions)
        )
        self._thread.start()
        self.send(
            "hello",
            payload={"protocol": 4, "decker_version": "x", "plugin_id": "com.decker.counter", "global_settings": {}},
        )
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

    def _card(self, **values: Any) -> dict[str, Any]:
        return {
            "context": "c1",
            "card": _CARD,
            "plugin": "com.decker.counter",
            "device": "d",
            "key": {"index": 0, "column": 0, "row": 0},
            "size": [_SIZE, _SIZE],
            "settings": _card_settings(**values),
            "last_paint": None,
        }

    def appear(self, **values: Any) -> None:
        card = self._card(**values)
        self.send(
            "will_appear",
            "c1",
            {
                "card": _CARD,
                "device": "d",
                "key": card["key"],
                "size": card["size"],
                "settings": card["settings"],
                "state": 0,
            },
        )

    def run_action(self, action_id: str, with_card: bool = True, **values: Any) -> dict:
        """Send run_action and return its action_result payload."""
        self._requests += 1
        request = f"r{self._requests}"
        self.send(
            "run_action",
            payload={
                "action": action_id,
                "request": request,
                "args": _args(action_id, **values),
                "input": "press" if with_card else "plugin",
                "called_at": "2026-11-21T10:00:00.123+00:00",
                "card": self._card() if with_card else None,
                "caller": None,
                "chain": "ch",
                "depth": 0,
            },
        )
        return self.recv_until("action_result")["payload"]

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


def _same_pixels(left: bytes, right: bytes) -> bool:
    a = Image.open(io.BytesIO(left)).convert("RGBA")
    b = Image.open(io.BytesIO(right)).convert("RGBA")
    return a.size == b.size and a.tobytes() == b.tobytes()


class TestManifest:
    def test_manifest_is_format_3_and_needs_decker_0_8_1(self):
        assert_that(_MANIFEST.format).is_equal_to(3)
        assert_that(_MANIFEST.version).is_equal_to("2.0.1")
        assert_that(_MANIFEST.decker).is_equal_to(">=0.8.1")
        assert_that(_MANIFEST.runtime.requirements).is_equal_to(("pillow>=12",))

    def test_default_bindings_press_double_long(self):
        bindings = _MANIFEST.cards[0].bindings

        assert_that(bindings["press"].action).is_equal_to(_INC)
        assert_that(dict(bindings["press"].args)).is_equal_to({"step": 1})
        assert_that(bindings["double_press"].action).is_equal_to(_DEC)
        assert_that(dict(bindings["double_press"].args)).is_equal_to({"step": 1})
        assert_that(bindings["long_press"].action).is_equal_to(_RESET)

    def test_actions_are_plugin_scoped_with_step_settings(self):
        assert_that({a.scope for a in _MANIFEST.actions}).is_equal_to({"plugin"})
        assert_that(_args(_INC)).is_equal_to({"step": 1})
        assert_that(_args(_DEC)).is_equal_to({"step": 1})
        assert_that(_args(_RESET)).is_equal_to({})

    def test_card_settings_keep_only_max(self):
        assert_that(_card_settings()).is_equal_to({"max": 0})
        assert_that(_card_settings(step=5, background="#102030")).is_equal_to({"max": 0})

    def test_manifest_declares_the_blue_background_default(self):
        assert_that(_MANIFEST.cards[0].appearance).is_equal_to({"background": "#1f618d"})


class TestCounting:
    def test_increment_adds_step_and_repaints(self, harness, counter):
        harness.appear()
        assert_that(_same_pixels(harness.next_png(), counter.render(0))).is_true()

        result = harness.run_action(_INC, step=3)

        assert_that(result["ok"]).is_true()
        assert_that(_same_pixels(harness.next_png(), counter.render(3))).is_true()
        harness.run_action(_INC, step=3)
        assert_that(_same_pixels(harness.next_png(), counter.render(6))).is_true()

    def test_decrement_subtracts_step(self, harness, counter):
        harness.appear()
        harness.next_png()
        harness.run_action(_INC, step=10)
        harness.next_png()

        harness.run_action(_DEC, step=4)

        assert_that(_same_pixels(harness.next_png(), counter.render(6))).is_true()

    def test_reset_returns_to_zero(self, harness, counter):
        harness.appear()
        harness.next_png()
        harness.run_action(_INC, step=4)
        harness.next_png()

        harness.run_action(_RESET)

        assert_that(_same_pixels(harness.next_png(), counter.render(0))).is_true()

    def test_max_wraps_to_zero(self, harness, counter):
        harness.appear(max=4)
        harness.next_png()

        harness.run_action(_INC, step=2)
        assert_that(_same_pixels(harness.next_png(), counter.render(2))).is_true()
        harness.run_action(_INC, step=2)
        assert_that(_same_pixels(harness.next_png(), counter.render(0))).is_true()

    def test_action_without_card_fails_cleanly(self, harness):
        result = harness.run_action(_INC, with_card=False)

        assert_that(result["ok"]).is_false()
        assert_that(result["error"]).is_equal_to("Counter actions need a card")

    def test_counter_never_sets_title(self, harness):
        harness.appear()
        harness.next_png()
        harness.run_action(_INC)
        harness.next_png()

        assert_that(harness.seen).does_not_contain("set_title")

    def test_settings_change_redraws(self, harness):
        harness.appear()
        harness.next_png()

        harness.send("settings_changed", "c1", {"settings": _card_settings(max=9)})

        assert_that(harness.next_png()).is_not_empty()

    def test_count_rendering_is_unchanged(self, harness, counter):
        harness.appear()
        harness.next_png()
        harness.run_action(_INC, step=42)

        assert_that(_same_pixels(harness.next_png(), counter.render(42))).is_true()


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

    def test_unopenable_font_file_falls_back(self, monkeypatch, tmp_path, recorder):
        broken = tmp_path / "DejaVuSans-Bold.ttf"
        broken.write_bytes(b"not a font")
        monkeypatch.setenv("DECKER_FONT_DIR", str(tmp_path))
        module = _load("decker_plugin_test_counter_broken")

        data = module.render(5)

        assert_that(recorder).contains(str(broken))
        assert_that(_has_ink(data)).is_true()

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
