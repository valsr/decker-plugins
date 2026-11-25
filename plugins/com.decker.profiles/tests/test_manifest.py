"""Manifest and packaging of the Profiles plugin (com.decker.profiles)."""

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
    assert_that(manifest.version).is_equal_to("3.0.0")
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


def test_no_cards_only_actions(manifest: PluginManifest) -> None:
    assert_that(manifest.cards).is_empty()
    assert_that(manifest.runtime).is_not_none()


def test_action_settings(manifest: PluginManifest) -> None:
    actions = {a.id: a for a in manifest.actions}
    for key in ("next", "previous"):
        wrap = _fields(actions[f"com.decker.profiles.{key}"])
        assert_that([(k, f.type, f.default) for k, f in wrap.items()]).is_equal_to([("wrap", "bool", False)])
    goto = _fields(actions["com.decker.profiles.goto"])
    assert_that([(k, f.type, f.default) for k, f in goto.items()]).is_equal_to([("profile", "profile", "")])


def test_icons_resolve(manifest: PluginManifest) -> None:
    assert_that(resolve_icon(_DIR, manifest.icon)).is_not_none()
    for spec in manifest.actions:
        assert_that(resolve_icon(_DIR, spec.icon)).is_not_none()


def test_packages_without_tests_or_assets(tmp_path: Path) -> None:
    staging = tmp_path / "plugins"
    shutil.copytree(_DIR, staging / _PLUGIN_ID)
    package = pack_all(staging, tmp_path / "dist")[0]

    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert_that(names).contains("manifest.json", "plugin.py")
    assert_that([n for n in names if n.startswith("tests/") or "/tests/" in n]).is_empty()
