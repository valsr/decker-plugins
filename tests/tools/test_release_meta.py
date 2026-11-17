import hashlib
import json
from pathlib import Path

from assertpy import assert_that

from tools.pack_all import pack_all
from tools.release_meta import release_url, version_entry, write_sidecar

from .conftest import PLUGINS


def test_version_entry_sha_and_size(tmp_path: Path) -> None:
    package = pack_all(PLUGINS, tmp_path)[0]
    data = package.read_bytes()

    entry = version_entry(package, "https://example.com/c.deckerplugin", "2026-11-16T19:00:00Z")

    assert_that(entry).is_equal_to(
        {
            "version": "1.0.0",
            "decker": ">=0.2",
            "url": "https://example.com/c.deckerplugin",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "released": "2026-11-16T19:00:00Z",
            "contributes": {"actions": ["Counter"], "icon_packs": ["Counter icons"]},
        }
    )


def test_write_sidecar_adds_plugin_id(tmp_path: Path) -> None:
    package = pack_all(PLUGINS, tmp_path)[0]

    sidecar = write_sidecar(package, "https://example.com/c", "2026-11-16T19:00:00Z")

    assert_that(sidecar.name).is_equal_to(package.name + ".json")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert_that(data).contains_entry({"id": "com.decker.counter"}, {"version": "1.0.0"})


def test_release_url_defaults_and_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert_that(release_url("com.x.y", "1.2.3")).is_equal_to(
        "https://github.com/valsr/decker-plugins/releases/download/com.x.y-v1.2.3/com.x.y-1.2.3.deckerplugin"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "fork/plugs")
    assert_that(release_url("com.x.y", "1.2.3")).starts_with("https://github.com/fork/plugs/releases/download/")
