"""Manifest, assets and packaging of the Profiles plugin (com.decker.profiles)."""

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from assertpy import assert_that
from decker.common.version import is_compatible
from decker.plugin.icons import resolve_icon
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import SettingField

from tools.pack_all import pack_all

_DIR = Path(__file__).parents[1]
_PLUGIN_ID = "com.decker.profiles"


@pytest.fixture(scope="module", name="manifest")
def manifest_fixture() -> PluginManifest:
    return PluginManifest.load(_DIR / "manifest.json")


def _fields(spec) -> dict[str, SettingField]:
    return {f.key: f for f in spec.settings if isinstance(f, SettingField)}


def test_manifest_is_format_3_with_global_actions(manifest: PluginManifest) -> None:
    assert_that(manifest.id).is_equal_to(_PLUGIN_ID)
    assert_that(manifest.name).is_equal_to("Profiles")
    assert_that(manifest.format).is_equal_to(3)
    assert_that(manifest.version).is_equal_to("2.0.0")
    assert_that(manifest.decker).is_equal_to(">=0.7")
    assert_that(is_compatible(manifest.decker, "0.6.0")).is_false()
    assert_that(is_compatible(manifest.decker, "0.7.0")).is_true()
    assert_that(manifest.runtime).is_not_none()
    assert_that(manifest.runtime.requirements).is_empty()  # type: ignore[union-attr]
    assert_that({a.id: a.scope for a in manifest.actions}).is_equal_to(
        {
            "com.decker.profiles.next": "global",
            "com.decker.profiles.previous": "global",
            "com.decker.profiles.goto": "global",
        }
    )


def test_three_cards_with_the_expected_ids_and_static_flags(manifest: PluginManifest) -> None:
    assert_that({a.id: a.static for a in manifest.cards}).is_equal_to(
        {
            "com.decker.profiles.next": False,
            "com.decker.profiles.previous": False,
            "com.decker.profiles.goto": False,
        }
    )


def test_action_and_card_settings(manifest: PluginManifest) -> None:
    cards = {c.id: c for c in manifest.cards}
    actions = {a.id: a for a in manifest.actions}
    for key in ("next", "previous"):
        wrap = _fields(actions[f"com.decker.profiles.{key}"])
        assert_that([(k, f.type, f.default) for k, f in wrap.items()]).is_equal_to([("wrap", "bool", False)])
        fields = _fields(cards[f"com.decker.profiles.{key}"])
        assert_that(list(fields)).is_equal_to(["color"])
        assert_that(fields["color"].type).is_equal_to("color")
        assert_that(fields["color"].extra["alpha"]).is_true()
        assert_that(fields["color"].default).is_equal_to("#ffffff")
        binding = cards[f"com.decker.profiles.{key}"].bindings["press"]
        assert_that(binding.action).is_equal_to(f"com.decker.profiles.{key}")
        assert_that(dict(binding.args)).is_equal_to({"wrap": False})
    goto = _fields(actions["com.decker.profiles.goto"])
    assert_that([(k, f.type, f.default) for k, f in goto.items()]).is_equal_to([("profile", "profile", "")])
    goto_card = cards["com.decker.profiles.goto"]
    assert_that(goto_card.settings).is_empty()
    assert_that(goto_card.bindings["press"].action).is_equal_to("com.decker.profiles.goto")


_CARET_SHA256 = {
    "caret-left.svg": "f95fa8fd4f2dccda0c4d7f4ae3d1cd80613d9afd82fc89dd3d3529511b61ca62",
    "caret-right.svg": "b9cf6c594d6a0ca9dc426107d3df78b7495dc136ad883dc5f0c80984dd7af77e",
}


@pytest.mark.parametrize("name", ["caret-left.svg", "caret-right.svg"])
def test_caret_assets_are_the_font_awesome_originals(name: str) -> None:
    raw = (_DIR / "assets" / name).read_bytes()
    assert_that(hashlib.sha256(raw).hexdigest()).is_equal_to(_CARET_SHA256[name])
    svg = raw.decode("utf-8")
    assert_that(svg).starts_with("<svg").contains("Font Awesome Free 7.3.1 by @fontawesome", 'fill="currentColor"')


def test_notice_credits_font_awesome() -> None:
    text = (_DIR / "assets" / "NOTICE.txt").read_text(encoding="utf-8")
    assert_that(text).contains("Font Awesome Free 7.3.1", "CC BY 4.0")


def test_icons_resolve(manifest: PluginManifest) -> None:
    assert_that(resolve_icon(_DIR, manifest.icon)).is_not_none()
    for spec in (*manifest.cards, *manifest.actions):
        assert_that(resolve_icon(_DIR, spec.icon)).is_not_none()


def test_packages_with_assets_and_without_tests(tmp_path: Path) -> None:
    staging = tmp_path / "plugins"
    shutil.copytree(_DIR, staging / _PLUGIN_ID)
    package = pack_all(staging, tmp_path / "dist")[0]

    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert_that(names).contains("manifest.json", "plugin.py", "assets/caret-left.svg", "assets/caret-right.svg")
    assert_that([n for n in names if n.startswith("tests/") or "/tests/" in n]).is_empty()
