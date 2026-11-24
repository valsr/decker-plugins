import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from decker.plugin.manifest import PluginManifest

from tools.pack_all import pack_all
from tools.release_meta import release_url, version_entry, write_sidecar

from .conftest import PLUGINS, write_plugin


def test_version_entry_sha_and_size(tmp_path: Path) -> None:
    package = pack_all(PLUGINS, tmp_path)[0]
    data = package.read_bytes()

    entry = version_entry(package, "https://example.com/c.deckerplugin", "2026-11-16T19:00:00Z")

    assert_that(entry).is_equal_to(
        {
            "version": "2.0.0",
            "decker": ">=0.7",
            "url": "https://example.com/c.deckerplugin",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "released": "2026-11-16T19:00:00Z",
            "contributes": {
                "cards": ["Counter"],
                "actions": ["Count up", "Count down", "Reset count"],
                "icon_packs": ["Counter icons"],
            },
        }
    )


def _entry_for_manifest_extras(tmp_path: Path, extras: dict[str, object]) -> dict[str, Any]:
    plugins = tmp_path / "plugins"
    folder = write_plugin(plugins, "com.example.demo", "1.0.0")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(extras)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = pack_all(plugins, tmp_path / "dist")[0]
    return version_entry(package, "https://example.com/d.deckerplugin", "2026-11-16T19:00:00Z")


@pytest.mark.skipif(
    "platforms" not in {f.name for f in dataclasses.fields(PluginManifest)},
    reason="needs a Decker with platform support (bump the pin)",
)
def test_version_entry_includes_declared_platforms(tmp_path: Path) -> None:
    linux = {"desktops": ["kde"], "sessions": ["wayland"]}

    entry = _entry_for_manifest_extras(tmp_path, {"platforms": ["linux", "macos"], "linux": linux})

    assert_that(entry).contains_entry({"platforms": ["linux", "macos"]}, {"linux": linux})


def test_version_entry_omits_platform_keys_when_undeclared(tmp_path: Path) -> None:
    entry = _entry_for_manifest_extras(tmp_path, {})

    assert_that(entry).does_not_contain_key("platforms").does_not_contain_key("linux")


def test_write_sidecar_adds_plugin_id(tmp_path: Path) -> None:
    package = pack_all(PLUGINS, tmp_path)[0]

    sidecar = write_sidecar(package, "https://example.com/c", "2026-11-16T19:00:00Z")

    assert_that(sidecar.name).is_equal_to(package.name + ".json")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert_that(data).contains_entry({"id": "com.decker.counter"}, {"version": "2.0.0"})


def test_release_url_defaults_and_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert_that(release_url("com.x.y", "1.2.3")).is_equal_to(
        "https://github.com/valsr/decker-plugins/releases/download/com.x.y-v1.2.3/com.x.y-1.2.3.deckerplugin"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "fork/plugs")
    assert_that(release_url("com.x.y", "1.2.3")).starts_with("https://github.com/fork/plugs/releases/download/")
