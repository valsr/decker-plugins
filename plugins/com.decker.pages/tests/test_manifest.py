"""Manifest, assets and packaging of the Pages plugin (com.decker.pages)."""

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
_FA = Path(__file__).parents[2] / "com.decker.fontawesome" / "solid"
_PLUGIN_ID = "com.decker.pages"


@pytest.fixture(scope="module", name="manifest")
def manifest_fixture() -> PluginManifest:
    return PluginManifest.load(_DIR / "manifest.json")


def _fields(spec) -> dict[str, SettingField]:
    return {f.key: f for f in spec.settings if isinstance(f, SettingField)}


def test_manifest_is_valid_and_gated_on_0_4(manifest: PluginManifest) -> None:
    assert_that(manifest.id).is_equal_to(_PLUGIN_ID)
    assert_that(manifest.name).is_equal_to("Pages")
    assert_that(manifest.version).is_equal_to("1.0.0")
    assert_that(manifest.decker).is_equal_to(">=0.4")
    assert_that(is_compatible(">=0.4", "0.3.0")).is_false()
    assert_that(is_compatible(manifest.decker, "0.4.0")).is_true()
    assert_that(manifest.runtime).is_not_none()
    assert_that(manifest.runtime.requirements).is_empty()  # type: ignore[union-attr]


def test_five_actions_with_the_expected_ids_and_static_flags(manifest: PluginManifest) -> None:
    assert_that({a.id: a.static for a in manifest.actions}).is_equal_to(
        {
            "com.decker.pages.next": False,
            "com.decker.pages.previous": False,
            "com.decker.pages.goto": False,
            "com.decker.pages.indicator": True,
            "com.decker.pages.name": True,
        }
    )


def test_runtime_action_settings(manifest: PluginManifest) -> None:
    specs = {a.id: a for a in manifest.actions}
    for key in ("next", "previous"):
        fields = _fields(specs[f"com.decker.pages.{key}"])
        assert_that(list(fields)).is_equal_to(["wrap", "color"])
        assert_that(fields["wrap"].type).is_equal_to("bool")
        assert_that(fields["wrap"].default).is_false()
        assert_that(fields["color"].type).is_equal_to("color")
        assert_that(fields["color"].extra["alpha"]).is_true()
        assert_that(fields["color"].default).is_equal_to("#ffffff")
    goto = _fields(specs["com.decker.pages.goto"])
    assert_that([(k, f.type) for k, f in goto.items()]).is_equal_to([("page", "page")])


def test_presets_are_static_with_templated_title_defaults(manifest: PluginManifest) -> None:
    specs = {a.id: a for a in manifest.actions}
    assert_that(specs["com.decker.pages.indicator"].appearance).is_equal_to(
        {"title": {"text": "{page_index} / {page_count}", "position": "middle", "size": 24}}
    )
    assert_that(specs["com.decker.pages.name"].appearance).is_equal_to(
        {"title": {"text": "{page_name}", "position": "middle", "size": 16}}
    )
    for key in ("indicator", "name"):
        assert_that(specs[f"com.decker.pages.{key}"].settings).is_empty()


@pytest.mark.parametrize("name", ["caret-left.svg", "caret-right.svg"])
def test_caret_assets_are_the_font_awesome_originals(name: str) -> None:
    assert_that((_DIR / "assets" / name).read_bytes()).is_equal_to((_FA / name).read_bytes())


def test_notice_credits_font_awesome() -> None:
    text = (_DIR / "assets" / "NOTICE.txt").read_text(encoding="utf-8")
    assert_that(text).contains("Font Awesome Free 7.3.1", "CC BY 4.0")


def test_icons_resolve(manifest: PluginManifest) -> None:
    assert_that(resolve_icon(_DIR, manifest.icon)).is_not_none()
    for spec in manifest.actions:
        assert_that(resolve_icon(_DIR, spec.icon)).is_not_none()


def test_packages_with_assets_and_without_tests(tmp_path: Path) -> None:
    staging = tmp_path / "plugins"
    shutil.copytree(_DIR, staging / _PLUGIN_ID)
    package = pack_all(staging, tmp_path / "dist")[0]

    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert_that(names).contains("manifest.json", "plugin.py", "assets/caret-left.svg", "assets/caret-right.svg")
    assert_that([n for n in names if n.startswith("tests/") or "/tests/" in n]).is_empty()
