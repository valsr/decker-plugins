import json
from pathlib import Path

from assertpy import assert_that
from decker.plugin.repository_index import parse_index

from tools.build_index import build_index
from tools.pack_all import pack_all
from tools.release_meta import version_entry

from .conftest import PLUGINS, write_plugin


def _counter_entry(tmp_path: Path) -> dict:
    package = pack_all(PLUGINS, tmp_path / "dist")[0]
    entry = version_entry(package, "https://example.com/counter-1.0.0.deckerplugin", "2026-11-16T19:00:00Z")
    return {"id": "com.decker.counter", **entry}


def test_build_index_parses_with_decker(tmp_path: Path) -> None:
    entry = _counter_entry(tmp_path)

    index_path = build_index([entry], PLUGINS, tmp_path / "site")

    parsed = parse_index(index_path.read_bytes(), "https://example.com/index.json")
    assert_that(parsed.plugins).is_length(1)
    plugin = parsed.plugins[0]
    assert_that(plugin.id).is_equal_to("com.decker.counter")
    assert_that(plugin.name).is_equal_to("Counter")
    assert_that(plugin.icon_url).is_equal_to("https://example.com/icons/com.decker.counter.png")
    assert_that(plugin.versions[0].sha256).is_equal_to(entry["sha256"])
    assert_that((tmp_path / "site" / "icons" / "com.decker.counter.png").is_file()).is_true()
    assert_that(json.loads(index_path.read_text(encoding="utf-8"))["format"]).is_equal_to(1)


def test_build_index_keeps_older_versions(tmp_path: Path) -> None:
    newer = {**_counter_entry(tmp_path), "version": "1.10.0"}
    older = {**newer, "version": "1.9.0"}
    oldest = {**newer, "version": "1.0.0"}

    index_path = build_index([oldest, newer, older], PLUGINS, tmp_path / "site")

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert_that(data["plugins"]).is_length(1)
    assert_that([v["version"] for v in data["plugins"][0]["versions"]]).is_equal_to(["1.10.0", "1.9.0", "1.0.0"])
    assert_that(data["plugins"][0]["versions"][0]).does_not_contain_key("id")


def test_build_index_skips_plugin_without_manifest(tmp_path: Path) -> None:
    write_plugin(tmp_path / "plugins", "com.example.demo", "1.0.0")
    entry = {**_counter_entry(tmp_path), "id": "com.example.gone"}

    index_path = build_index([entry], tmp_path / "plugins", tmp_path / "site")

    assert_that(json.loads(index_path.read_text(encoding="utf-8"))["plugins"]).is_empty()


def test_build_index_skips_unparseable_version_with_warning(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    good = _counter_entry(tmp_path)
    bad = {**good, "version": "1.0.0-foo"}

    index_path = build_index([good, bad], PLUGINS, tmp_path / "site")

    versions = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]["versions"]
    assert_that([v["version"] for v in versions]).is_equal_to(["1.0.0"])
    assert_that(capsys.readouterr().err).contains("1.0.0-foo")
