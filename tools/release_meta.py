"""Build the index `versions[]` entry for a package and write it as the `<package>.json` release sidecar."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from decker.plugin.package import read_manifest

DEFAULT_REPOSITORY = "valsr/decker-plugins"


def repository() -> str:
    """The `owner/repo` slug: GITHUB_REPOSITORY in CI, the upstream repository otherwise."""
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY


def release_url(plugin_id: str, version: str) -> str:
    """Stable download URL of the package attached to the release `<id>-v<version>`."""
    return (
        f"https://github.com/{repository()}/releases/download/{plugin_id}-v{version}/{plugin_id}-{version}.deckerplugin"
    )


def version_entry(package: Path, url: str, released: str) -> dict[str, Any]:
    """The index version entry for a package: version, decker, platform keys (if declared), url, size, sha256, etc."""
    data = package.read_bytes()
    manifest = read_manifest(data)
    contributes = {
        kind: names
        for kind, names in (
            ("actions", [a.name for a in manifest.actions]),
            ("icon_packs", [p.name for p in manifest.icon_packs]),
        )
        if names
    }
    entry: dict[str, Any] = {"version": manifest.version}
    if manifest.decker:
        entry["decker"] = manifest.decker
    # The repo pins a Decker that may predate platform support, so the attribute may not exist.
    platforms = getattr(manifest, "platforms", None)
    if platforms:
        entry.update(platforms.to_payload())
    entry.update(
        url=url,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        released=released,
        contributes=contributes,
    )
    return entry


def write_sidecar(package: Path, url: str, released: str) -> Path:
    """Write `<package>.json`: the version entry plus the plugin `id`, so the index can be rebuilt from releases."""
    entry = {"id": read_manifest(package.read_bytes()).id, **version_entry(package, url, released)}
    sidecar = package.with_name(package.name + ".json")
    sidecar.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return sidecar


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--url", help="download URL; defaults to the GitHub release URL of this repository")
    parser.add_argument("--released", help="timestamp; defaults to now (UTC)")
    args = parser.parse_args()
    manifest = read_manifest(args.package.read_bytes())
    url = args.url or release_url(manifest.id, manifest.version)
    released = args.released or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(write_sidecar(args.package, url, released))


if __name__ == "__main__":
    main()
