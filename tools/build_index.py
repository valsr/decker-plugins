"""Build the repository site: `index.json` (format 1) plus `icons/<id>.png` from release sidecars and manifests."""

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from decker.asset.renderer import AssetRenderer

from tools.versioning import parse_plugin_version

INDEX_NAME = "Decker Plugins"
ICON_SIZE = 256  # px; the rendered size of an SVG manifest icon


def _icon_source(folder: Path, icon: str | None) -> Path | None:
    if not icon:
        return None
    for candidate in (folder / icon, folder / f"{icon}.png", folder / f"{icon}.svg"):
        if candidate.is_file():
            return candidate
    return None


def _write_icon(source: Path, destination: Path, plugin_id: str) -> bool:
    """Write `destination` as a PNG: an SVG source is rendered at ICON_SIZE, a PNG source is copied unchanged."""
    try:
        if source.suffix.lower() == ".svg":
            AssetRenderer().render_path(source, ICON_SIZE, ICON_SIZE).save(destination, format="PNG")
        else:
            shutil.copyfile(source, destination)
    except Exception as exc:  # noqa: BLE001  (a broken icon must not stop the index being built)
        print(f"warning: skipping the icon of {plugin_id}: {exc}", file=sys.stderr)
        destination.unlink(missing_ok=True)
        return False
    return True


def build_index(entries: list[dict[str, Any]], plugins_dir: Path, out_dir: Path, generated: str | None = None) -> Path:
    """Group sidecar entries (each carrying its plugin `id`) by plugin and write `out_dir/index.json`.

    Plugin metadata comes from the current manifest in plugins_dir; entries of a plugin that no longer exists there
    are skipped. Versions are newest first.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        version = {key: value for key, value in entry.items() if key != "id"}
        try:
            parse_plugin_version(version.get("version"))
        except ValueError as exc:
            print(f"warning: skipping {entry['id']} entry: {exc}", file=sys.stderr)
            continue
        grouped.setdefault(entry["id"], []).append(version)

    out_dir.mkdir(parents=True, exist_ok=True)
    plugins = []
    for plugin_id in sorted(grouped):
        folder = plugins_dir / plugin_id
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            print(f"warning: no manifest for {plugin_id}, skipping it", file=sys.stderr)
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugin: dict[str, Any] = {"id": plugin_id, "name": manifest.get("name", plugin_id)}
        for key in ("author", "description", "category", "homepage"):
            if manifest.get(key):
                plugin[key] = manifest[key]
        icon = _icon_source(folder, manifest.get("icon"))
        if icon is not None:
            (out_dir / "icons").mkdir(exist_ok=True)
            if _write_icon(icon, out_dir / "icons" / f"{plugin_id}.png", plugin_id):
                plugin["icon"] = f"icons/{plugin_id}.png"
        plugin["versions"] = sorted(grouped[plugin_id], key=lambda v: parse_plugin_version(v["version"]), reverse=True)
        plugins.append(plugin)

    index = {
        "format": 1,
        "name": INDEX_NAME,
        "generated": generated or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": plugins,
    }
    path = out_dir / "index.json"
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path


def load_sidecars(sidecar_dir: Path) -> list[dict[str, Any]]:
    """Read every `*.json` sidecar below sidecar_dir."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(sidecar_dir.rglob("*.json"))]


def main() -> None:
    root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecars", type=Path, required=True, help="folder with downloaded `<package>.json` files")
    parser.add_argument("--plugins", type=Path, default=root / "plugins")
    parser.add_argument("--out", type=Path, default=root / "site")
    args = parser.parse_args()
    print(build_index(load_sidecars(args.sidecars), args.plugins, args.out))


if __name__ == "__main__":
    main()
