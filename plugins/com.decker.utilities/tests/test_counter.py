"""Tests for the Counter card and actions of the Utilities plugin, run through the SDK loop on pipes."""

import base64
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import apply_schema
from decker.server.fonts import BUNDLED_FONT_DIR
from decker_plugin_sdk import _actions, _runtime
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from _harness import PLUGIN_DIR, Harness, load_plugin  # noqa: E402

_CARD = "com.decker.utilities.counter"
_MANIFEST = PluginManifest.load(PLUGIN_DIR / "manifest.json")
_CARD_SCHEMA = next(c for c in _MANIFEST.cards if c.id == _CARD).settings
_ACTIONS = {spec.id: spec for spec in _MANIFEST.actions}
_INC = "com.decker.utilities.counter-increment"
_DEC = "com.decker.utilities.counter-decrement"
_RESET = "com.decker.utilities.counter-reset"
_MODULE = PLUGIN_DIR / "counter_card.py"


@pytest.fixture(scope="module", name="counter")
def counter_fixture() -> ModuleType:
    load_plugin()
    return sys.modules["counter_card"]


def _load_fresh(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """counter_card.py imported again from its file, without replacing the registered card and actions."""
    monkeypatch.setattr(_actions, "_ACTIONS", dict(_actions._ACTIONS))
    monkeypatch.setattr(_runtime, "_REGISTRY", dict(_runtime._REGISTRY))
    spec = importlib.util.spec_from_file_location(name, _MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _card_settings(**values: Any) -> dict[str, Any]:
    return apply_schema(_CARD_SCHEMA, values)


def _args(action_id: str, **values: Any) -> dict[str, Any]:
    return apply_schema(_ACTIONS[action_id].settings, values)


class CounterHarness:
    """The shared Harness with the Counter conveniences these tests need."""

    def __init__(self) -> None:
        self.base = Harness(load_plugin(), _CARD, "CounterCard")

    def appear(self, **values: Any) -> None:
        self.base.appear(_card_settings(**values))

    def run_action(self, action_id: str, with_card: bool = True, **values: Any) -> dict:
        return self.base.run_action(action_id, _args(action_id, **values), with_card)

    def next_png(self) -> bytes:
        return base64.b64decode(self.base.recv_until("set_image")["payload"]["image"])


@pytest.fixture(name="harness")
def harness_fixture():
    harness = CounterHarness()
    yield harness
    harness.base.close()


def _same_pixels(left: bytes, right: bytes) -> bool:
    a = Image.open(io.BytesIO(left)).convert("RGBA")
    b = Image.open(io.BytesIO(right)).convert("RGBA")
    return a.size == b.size and a.tobytes() == b.tobytes()


class TestManifest:
    def test_default_bindings_press_double_long(self):
        bindings = next(c for c in _MANIFEST.cards if c.id == _CARD).bindings

        assert_that(bindings["press"].action).is_equal_to(_INC)
        assert_that(dict(bindings["press"].args)).is_equal_to({"step": 1})
        assert_that(bindings["double_press"].action).is_equal_to(_DEC)
        assert_that(dict(bindings["double_press"].args)).is_equal_to({"step": 1})
        assert_that(bindings["long_press"].action).is_equal_to(_RESET)

    def test_actions_are_plugin_scoped_with_step_settings(self):
        assert_that({_ACTIONS[a].scope for a in (_INC, _DEC, _RESET)}).is_equal_to({"plugin"})
        assert_that(_args(_INC)).is_equal_to({"step": 1})
        assert_that(_args(_DEC)).is_equal_to({"step": 1})
        assert_that(_args(_RESET)).is_equal_to({})

    def test_card_settings_keep_only_max(self):
        assert_that(_card_settings()).is_equal_to({"max": 0})
        assert_that(_card_settings(step=5, background="#102030")).is_equal_to({"max": 0})

    def test_manifest_declares_the_blue_background_default(self):
        assert_that(next(c for c in _MANIFEST.cards if c.id == _CARD).appearance).is_equal_to({"background": "#1f618d"})


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

        assert_that(harness.base.seen).does_not_contain("set_title")

    def test_settings_change_redraws(self, harness):
        harness.appear()
        harness.next_png()

        harness.base.change(_card_settings(max=9))

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
        module = _load_fresh("decker_plugin_test_utilities_counter_sdk", monkeypatch)

        data = module.render(5)

        assert_that(recorder).is_equal_to([str(BUNDLED_FONT_DIR / "DejaVuSans-Bold.ttf")])
        assert_that(_has_ink(data)).is_true()

    def test_no_font_dir_falls_back_to_the_default_font(self, monkeypatch, recorder):
        monkeypatch.delenv("DECKER_FONT_DIR", raising=False)
        module = _load_fresh("decker_plugin_test_utilities_counter_nodir", monkeypatch)

        data = module.render(5)

        assert_that(recorder).is_empty()
        assert_that(_has_ink(data)).is_true()

    def test_unopenable_font_file_falls_back(self, monkeypatch, tmp_path, recorder):
        broken = tmp_path / "DejaVuSans-Bold.ttf"
        broken.write_bytes(b"not a font")
        monkeypatch.setenv("DECKER_FONT_DIR", str(tmp_path))
        module = _load_fresh("decker_plugin_test_utilities_counter_broken", monkeypatch)

        data = module.render(5)

        assert_that(recorder).contains(str(broken))
        assert_that(_has_ink(data)).is_true()

    def test_missing_sdk_fonts_module_falls_back(self, monkeypatch, recorder):
        monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED_FONT_DIR))
        monkeypatch.setitem(sys.modules, "decker_plugin_sdk.fonts", None)  # makes the import raise ImportError
        module = _load_fresh("decker_plugin_test_utilities_counter_noimport", monkeypatch)

        data = module.render(5)

        assert_that(recorder).is_empty()
        assert_that(_has_ink(data)).is_true()

    def test_plugin_no_longer_imports_subprocess(self, counter):
        assert_that(hasattr(counter, "subprocess")).is_false()
        assert_that(_MODULE.read_text()).does_not_contain("subprocess").does_not_contain("fc-match")
