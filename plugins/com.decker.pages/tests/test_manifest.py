"""Manifest and packaging of the Pages plugin (com.decker.pages)."""

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
_NOTHING = "com.decker.core.nothing"
_PLUGIN_ID = "com.decker.pages"


@pytest.fixture(scope="module", name="manifest")
def manifest_fixture() -> PluginManifest:
    return PluginManifest.load(_DIR / "manifest.json")


def _fields(spec) -> dict[str, SettingField]:
    return {f.key: f for f in spec.settings if isinstance(f, SettingField)}


def test_manifest_is_format_3_with_global_actions(manifest: PluginManifest) -> None:
    assert_that(manifest.id).is_equal_to(_PLUGIN_ID)
    assert_that(manifest.name).is_equal_to("Pages")
    assert_that(manifest.format).is_equal_to(3)
    assert_that(manifest.version).is_equal_to("3.1.0")
    assert_that(manifest.decker).is_equal_to(">=0.8")
    assert_that(is_compatible(manifest.decker, "0.7.2")).is_false()
    assert_that(is_compatible(manifest.decker, "0.8.0")).is_true()
    assert_that(manifest.runtime).is_not_none()
    assert_that(manifest.runtime.requirements).is_empty()  # type: ignore[union-attr]
    assert_that({a.id: a.scope for a in manifest.actions}).is_equal_to(
        {
            "com.decker.pages.next": "global",
            "com.decker.pages.previous": "global",
            "com.decker.pages.goto": "global",
        }
    )


def test_no_cards_only_actions(manifest: PluginManifest) -> None:
    assert_that(manifest.cards).is_empty()
    assert_that(manifest.runtime).is_not_none()


def test_action_settings(manifest: PluginManifest) -> None:
    actions = {a.id: a for a in manifest.actions}
    for key in ("next", "previous"):
        wrap = _fields(actions[f"com.decker.pages.{key}"])
        assert_that([(k, f.type, f.default) for k, f in wrap.items()]).is_equal_to([("wrap", "bool", False)])
    goto = _fields(actions["com.decker.pages.goto"])
    assert_that([(k, f.type, f.default) for k, f in goto.items()]).is_equal_to(
        [("profile", "profile", ""), ("page", "page", "")]
    )
    assert_that(goto["page"].extra["profile_field"]).is_equal_to("profile")


def test_presets_are_declared(manifest: PluginManifest) -> None:
    by_id = {p.id: p for p in manifest.presets}
    presets = {
        pid: (p.name, b.action, dict(b.args), p.icon)
        for pid, p in by_id.items()
        if (b := p.bindings.get("press")) is not None and b.action != _NOTHING
    }
    assert_that(presets).is_equal_to(
        {
            "com.decker.pages.preset-next": ("Next page", "com.decker.pages.next", {"wrap": True}, "fas:forward"),
            "com.decker.pages.preset-previous": (
                "Previous page",
                "com.decker.pages.previous",
                {"wrap": True},
                "fas:backward",
            ),
            "com.decker.pages.preset-goto": ("Go to page", "com.decker.pages.goto", {}, "fas:file"),
        }
    )
    assert_that({b.action for b in by_id["com.decker.pages.preset-name"].bindings.values()}).is_subset_of({_NOTHING})
    assert_that({b.action for b in by_id["com.decker.pages.preset-count"].bindings.values()}).is_subset_of({_NOTHING})
    for preset in by_id.values():
        icon = preset.appearance.get("icon")
        if icon is not None:
            assert_that(icon).is_equal_to({"ref": preset.icon, "color": "#ffffff"})
    assert_that(len(by_id)).is_equal_to(5)


def test_page_name_and_count_titles(manifest: PluginManifest) -> None:
    by_id = {p.id: p for p in manifest.presets}
    assert_that(by_id["com.decker.pages.preset-name"].name).is_equal_to("Page Name")
    assert_that(by_id["com.decker.pages.preset-name"].appearance["title"]).is_equal_to(
        {"text": "{page_name}", "position": "middle", "size": 16}
    )
    assert_that(by_id["com.decker.pages.preset-count"].name).is_equal_to("Page Count")
    assert_that(by_id["com.decker.pages.preset-count"].appearance["title"]).is_equal_to(
        {"text": "{page_index} / {page_count}", "position": "middle", "size": 24}
    )


def test_presets_load_with_the_pinned_decker(manifest: PluginManifest) -> None:
    ids = [p.id for p in manifest.presets] + [a.id for a in manifest.actions]
    assert_that(ids).does_not_contain_duplicates()
    assert_that(manifest.cards).is_empty()
    for preset in manifest.presets:
        for binding in preset.bindings.values():
            assert_that(binding.action).is_in(_NOTHING, *(a.id for a in manifest.actions))


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
