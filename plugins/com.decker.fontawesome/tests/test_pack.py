"""Tests for the Font Awesome icon pack plugin (com.decker.fontawesome): manifest, icons and packaging."""

import shutil
import zipfile
from pathlib import Path

import pytest
from assertpy import assert_that
from decker.asset.iconpack import IconPackRegistry
from decker.asset.renderer import AssetRenderer
from decker.plugin.icons import max_icon_bytes, resolve_icon
from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest

from tools.pack_all import pack_all

_DIR = Path(__file__).parents[1]
_PLUGIN_ID = "com.decker.fontawesome"


@pytest.fixture(scope="module", name="manifest")
def manifest_fixture() -> PluginManifest:
    return PluginManifest.load(_DIR / "manifest.json")


@pytest.fixture(scope="module", name="registry")
def registry_fixture(manifest: PluginManifest) -> IconPackRegistry:
    failures: list[str] = []
    registry = IconPackRegistry(on_failure=lambda plugin_id, message: failures.append(f"{plugin_id}: {message}"))
    registry.register(InstalledPlugin(manifest, _DIR))
    assert_that(failures).is_empty()
    return registry


def test_manifest_is_valid_and_named(manifest: PluginManifest) -> None:
    assert_that(manifest.id).is_equal_to(_PLUGIN_ID)
    assert_that(manifest.name).is_equal_to("Fontawesome Icons")
    assert_that(manifest.description).is_not_empty().is_equal_to(manifest.description.strip())
    assert_that(manifest.cards).is_empty()
    assert_that(manifest.icon_packs).is_length(3)


def test_every_declared_pack_folder_exists_and_has_icons(manifest: PluginManifest) -> None:
    for spec in manifest.icon_packs:
        folder = _DIR / spec.path
        assert_that(folder.is_dir()).described_as(spec.path).is_true()
        assert_that(list(folder.glob("*.svg"))).described_as(spec.path).is_not_empty()


def test_pack_ids_start_with_plugin_id(manifest: PluginManifest) -> None:
    for spec in manifest.icon_packs:
        assert_that(spec.id).starts_with(f"{_PLUGIN_ID}.")
    assert_that({spec.id for spec in manifest.icon_packs}).is_length(3)


def test_manifest_icon_resolves(manifest: PluginManifest) -> None:
    assert_that(resolve_icon(_DIR, manifest.icon)).is_not_none()


def test_every_icon_is_readable_within_the_size_cap(manifest: PluginManifest, registry: IconPackRegistry) -> None:
    for spec in manifest.icon_packs:
        names = registry.list_icons(spec.id)
        assert_that(names).described_as(spec.id).is_not_empty()
        unreadable = [name for name in names if registry.read_icon(spec.id, name) is None]
        assert_that(unreadable).described_as(f"{spec.id} unreadable").is_empty()
        biggest = max((_DIR / spec.path / name).stat().st_size for name in names)
        assert_that(biggest).is_less_than_or_equal_to(max_icon_bytes())


def test_every_svg_renders(manifest: PluginManifest, registry: IconPackRegistry) -> None:
    renderer = AssetRenderer()
    broken = []
    for spec in manifest.icon_packs:
        for name in registry.list_icons(spec.id):
            data = registry.read_icon(spec.id, name)
            assert data is not None
            if renderer.render_bytes(data, 48, 48) is None:
                broken.append(f"{spec.id}/{name}")
    assert_that(broken).is_empty()


def test_pack_icons_follow_the_current_colour(registry: IconPackRegistry) -> None:
    """Font Awesome icons use currentColor, which is what the Icon plugin's fill colour recolours."""
    data = registry.read_icon("com.decker.fontawesome.solid", "house.svg")
    assert data is not None
    assert_that(data).contains(b"currentColor")


def test_license_is_shipped() -> None:
    text = (_DIR / "LICENSE.txt").read_text(encoding="utf-8")
    assert_that(text).contains("Font Awesome Free License")


def test_packages_without_tests_and_within_limits(tmp_path: Path) -> None:
    staging = tmp_path / "plugins"
    shutil.copytree(_DIR, staging / _PLUGIN_ID)
    package = pack_all(staging, tmp_path / "dist")[0]

    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert_that(package.stat().st_size).is_less_than(64 * 1024 * 1024)
    assert_that(len(names)).is_less_than(10_000)
    assert_that([n for n in names if n.startswith("tests/") or "/tests/" in n]).is_empty()
    assert_that(names).contains("manifest.json", "LICENSE.txt")
