"""Fail when a plugin changed relative to a base ref without a higher manifest version than its latest release tag."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

from tools.versioning import parse_plugin_version


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout


def _changed_plugins(repo: Path, base_ref: str) -> list[str]:
    """Plugin folder names with any difference between the merge base of base_ref and HEAD, or the working tree."""
    names: set[str] = set()
    for diff in ((f"{base_ref}...HEAD",), ("HEAD",)):
        for line in _git(repo, "diff", "--name-only", *diff, "--", "plugins").splitlines():
            parts = line.split("/")
            if len(parts) > 2 and parts[2] != "tests":  # tests are not packaged
                names.add(parts[1])
    return sorted(names)


def _highest_tag(repo: Path, plugin_id: str) -> Version | None:
    prefix = f"{plugin_id}-v"
    versions = []
    # A tag on HEAD is this very commit's own release (publish may have run before this check), not a prior one.
    own = set(_git(repo, "tag", "--list", "--points-at", "HEAD", f"{prefix}*").splitlines())
    for tag in _git(repo, "tag", "--list", f"{prefix}*").splitlines():
        if tag in own:
            continue
        text = tag.removeprefix(prefix)
        try:
            versions.append(parse_plugin_version(text))
        except ValueError:
            continue  # not a release tag of ours
    return max(versions, default=None)


def check_versions(repo: Path, base_ref: str) -> list[str]:
    """Return error messages for plugins changed vs base_ref whose version is invalid or not above the latest tag."""
    errors = []
    for folder in _changed_plugins(repo, base_ref):
        manifest_path = repo / "plugins" / folder / "manifest.json"
        if not manifest_path.is_file():
            continue  # plugin removed
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{folder}: cannot read manifest.json: {exc}")
            continue
        plugin_id = data.get("id")
        if plugin_id != folder:
            errors.append(f"{folder}: manifest id {plugin_id!r} does not match the folder name")
            continue
        text = data.get("version")
        try:
            current = parse_plugin_version(text)
        except ValueError as exc:
            errors.append(f"{folder}: manifest version: {exc}")
            continue
        latest = _highest_tag(repo, plugin_id)
        if latest is not None and current <= latest:
            errors.append(
                f"{folder}: files changed but manifest version {text} is not greater than the latest release {latest}"
            )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_ref", help="git ref to compare against, for example origin/main")
    parser.add_argument("--repo", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    errors = check_versions(args.repo, args.base_ref)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
