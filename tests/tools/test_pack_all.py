import zipfile
from pathlib import Path

from assertpy import assert_that

from tools.pack_all import pack_all

from .conftest import PLUGINS


def test_pack_all_packs_counter(tmp_path: Path) -> None:
    packages = pack_all(PLUGINS, tmp_path)

    assert_that([p.name for p in packages]).is_equal_to(["com.decker.counter-1.0.0.deckerplugin"])
    with zipfile.ZipFile(packages[0]) as zf:
        assert_that(zf.namelist()).contains("manifest.json", "plugin.py")
        assert_that([n for n in zf.namelist() if n.startswith("tests")]).is_empty()


def test_pack_all_ignores_non_plugin_entries(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "README.md").write_text("x", encoding="utf-8")

    assert_that(pack_all(plugins, tmp_path / "out")).is_empty()


def test_pack_all_cli_prints_manifest_id_and_version(tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tools import pack_all as module

    monkeypatch.setattr("sys.argv", ["pack_all", "--out", str(tmp_path)])
    module.main()

    assert_that(capsys.readouterr().out.strip()).is_equal_to(
        f"com.decker.counter 1.0.0 {tmp_path / 'com.decker.counter-1.0.0.deckerplugin'}"
    )
