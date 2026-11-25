import io
import json
from pathlib import Path

from assertpy import assert_that
from decker.plugin.repository_index import parse_index
from PIL import Image

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


def test_build_index_keeps_platform_keys_on_versions(tmp_path: Path) -> None:
    linux = {"desktops": ["kde"], "sessions": ["wayland"]}
    entry = {**_counter_entry(tmp_path), "platforms": ["linux", "macos"], "linux": linux}

    index_path = build_index([entry], PLUGINS, tmp_path / "site")

    version = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]["versions"][0]
    assert_that(version).contains_entry({"platforms": ["linux", "macos"]}, {"linux": linux})


def test_build_index_skips_plugin_without_manifest(tmp_path: Path) -> None:
    write_plugin(tmp_path / "plugins", "com.example.demo", "1.0.0")
    entry = {**_counter_entry(tmp_path), "id": "com.example.gone"}

    index_path = build_index([entry], tmp_path / "plugins", tmp_path / "site")

    assert_that(json.loads(index_path.read_text(encoding="utf-8"))["plugins"]).is_empty()


def test_build_index_skips_unparseable_version_with_warning(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    good = _counter_entry(tmp_path)
    bad = {**good, "version": "1.2.0-foo"}

    index_path = build_index([good, bad], PLUGINS, tmp_path / "site")

    versions = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]["versions"]
    assert_that([v["version"] for v in versions]).is_equal_to(["2.0.2"])
    assert_that(capsys.readouterr().err).contains("1.2.0-foo")


_SQUARE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="red"/></svg>'
)


def _icon_plugin(tmp_path: Path, icon: str, files: dict[str, bytes]) -> tuple[Path, dict]:
    plugins = tmp_path / "plugins"
    folder = write_plugin(plugins, "com.example.demo", "1.0.0")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["icon"] = icon
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return plugins, {"id": "com.example.demo", "version": "1.0.0"}


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _built_icon(site: Path) -> Image.Image:
    return Image.open(site / "icons" / "com.example.demo.png")


def test_svg_manifest_icon_is_rendered_to_png(tmp_path: Path) -> None:
    plugins, entry = _icon_plugin(tmp_path, "brands/mark", {"brands/mark.svg": _SQUARE_SVG.encode()})

    index_path = build_index([entry], plugins, tmp_path / "site")

    image = _built_icon(tmp_path / "site")
    assert_that(image.format).is_equal_to("PNG")
    assert_that(image.size).is_equal_to((256, 256))
    assert_that(image.convert("RGBA").getpixel((128, 128))).is_equal_to((255, 0, 0, 255))
    plugin = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]
    assert_that(plugin["icon"]).is_equal_to("icons/com.example.demo.png")


def test_svg_icon_path_with_extension_is_supported(tmp_path: Path) -> None:
    plugins, entry = _icon_plugin(tmp_path, "mark.svg", {"mark.svg": _SQUARE_SVG.encode()})

    build_index([entry], plugins, tmp_path / "site")

    assert_that(_built_icon(tmp_path / "site").format).is_equal_to("PNG")


def test_png_manifest_icon_is_copied_unchanged(tmp_path: Path) -> None:
    source = _png_bytes()
    plugins, entry = _icon_plugin(tmp_path, "mark", {"mark.png": source})

    build_index([entry], plugins, tmp_path / "site")

    assert_that((tmp_path / "site" / "icons" / "com.example.demo.png").read_bytes()).is_equal_to(source)


def test_font_awesome_manifest_icon_is_rendered_to_png(tmp_path: Path) -> None:
    plugins, entry = _icon_plugin(tmp_path, "fas:toolbox", {})

    index_path = build_index([entry], plugins, tmp_path / "site")

    image = _built_icon(tmp_path / "site").convert("RGBA")
    assert_that(image.size).is_equal_to((256, 256))
    glyph = [px for px in image.getdata() if px[3] == 255]
    assert_that(glyph).is_not_empty()
    assert_that(set(glyph)).is_equal_to({(128, 128, 128, 255)})
    plugin = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]
    assert_that(plugin["icon"]).is_equal_to("icons/com.example.demo.png")


def test_unknown_font_awesome_icon_is_skipped_with_warning(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    plugins, entry = _icon_plugin(tmp_path, "fas:no-such-icon", {})

    index_path = build_index([entry], plugins, tmp_path / "site")

    plugin = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]
    assert_that(plugin).does_not_contain_key("icon")
    assert_that(capsys.readouterr().err).contains("no-such-icon")


def test_unrenderable_svg_is_skipped_with_warning(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    plugins, entry = _icon_plugin(tmp_path, "mark", {"mark.svg": b"<svg xmlns='http://www.w3.org/2000/svg'><"})

    index_path = build_index([entry], plugins, tmp_path / "site")

    plugin = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]
    assert_that(plugin).does_not_contain_key("icon")
    assert_that((tmp_path / "site" / "icons" / "com.example.demo.png").exists()).is_false()
    assert_that(capsys.readouterr().err).contains("icon").contains("com.example.demo")


def test_missing_icon_file_is_omitted(tmp_path: Path) -> None:
    plugins, entry = _icon_plugin(tmp_path, "nowhere", {})

    index_path = build_index([entry], plugins, tmp_path / "site")

    assert_that(json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]).does_not_contain_key("icon")


def test_importing_the_builder_does_not_load_the_svg_renderer() -> None:
    import subprocess
    import sys

    code = "import tools.build_index, sys; print('decker.asset.renderer' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=Path(__file__).parents[2]
    )
    assert_that(result.stdout.strip()).is_equal_to("False")


def test_missing_cairo_skips_the_svg_icon_but_still_builds_the_index(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def no_cairo(*_args: object, **_kwargs: object) -> None:
        raise OSError("no library called 'cairo-2' was found")

    monkeypatch.setattr("decker.asset.renderer.AssetRenderer", no_cairo)
    plugins, entry = _icon_plugin(tmp_path, "mark", {"mark.svg": _SQUARE_SVG.encode()})

    index_path = build_index([entry], plugins, tmp_path / "site")

    plugin = json.loads(index_path.read_text(encoding="utf-8"))["plugins"][0]
    assert_that(plugin).does_not_contain_key("icon")
    assert_that(plugin["versions"]).is_length(1)
    assert_that(capsys.readouterr().err).contains("cairo")
