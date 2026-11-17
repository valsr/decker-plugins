"""Pack every plugin under plugins/ into `<id>-<version>.deckerplugin` using Decker's own packer."""

import argparse
from pathlib import Path

from decker.cli.plugin_scaffold import pack


def pack_all(plugins_dir: Path, out_dir: Path) -> list[Path]:
    """Pack each plugin folder (one holding a manifest.json) and return the packages, sorted by folder name."""
    packages = []
    for folder in sorted(plugins_dir.iterdir()):
        if folder.is_dir() and (folder / "manifest.json").is_file():
            packages.append(pack(folder, out_dir))
    return packages


def main() -> None:
    root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, default=root / "plugins")
    parser.add_argument("--out", type=Path, default=root / "dist")
    args = parser.parse_args()
    for package in pack_all(args.plugins, args.out):
        print(package)


if __name__ == "__main__":
    main()
