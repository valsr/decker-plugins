"""Pack every plugin under plugins/ into `<id>-<version>.deckerplugin` using Decker's own packer.

Prints one `<id> <version> <package path>` line per package (id and version come from the manifest).
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from decker.cli.plugin_scaffold import pack
from decker.plugin.package import read_manifest

# Dev-only top-level entries that are not shipped in the package.
_DEV_ONLY = ("tests", ".pytest_cache", ".ruff_cache")


def pack_all(plugins_dir: Path, out_dir: Path) -> list[Path]:
    """Pack each plugin folder (one holding a manifest.json) without its tests; return packages sorted by folder."""
    packages = []
    for folder in sorted(plugins_dir.iterdir()):
        if folder.is_dir() and (folder / "manifest.json").is_file():
            with tempfile.TemporaryDirectory() as staging:
                staged = Path(staging) / folder.name
                shutil.copytree(folder, staged, ignore=shutil.ignore_patterns(*_DEV_ONLY))
                packages.append(pack(staged, out_dir))
    return packages


def main() -> None:
    root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, default=root / "plugins")
    parser.add_argument("--out", type=Path, default=root / "dist")
    args = parser.parse_args()
    for package in pack_all(args.plugins, args.out):
        manifest = read_manifest(package.read_bytes())
        print(f"{manifest.id} {manifest.version} {package}")


if __name__ == "__main__":
    main()
