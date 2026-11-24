import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
PLUGINS = REPO / "plugins"
COUNTER = PLUGINS / "com.decker.counter"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def write_plugin(plugins_dir: Path, plugin_id: str, version: str) -> Path:
    folder = plugins_dir / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": 3,
        "id": plugin_id,
        "name": "Demo",
        "version": version,
        "author": "Me",
        "contributes": {"icon_packs": [{"id": f"{plugin_id}.icons", "name": "Demo icons", "path": "pack"}]},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "pack").mkdir(exist_ok=True)
    (folder / "pack" / "a.png").write_bytes(b"x")
    return folder


@pytest.fixture(name="git_repo")
def git_repo_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write_plugin(repo / "plugins", "com.example.demo", "1.0.0")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "tag", "com.example.demo-v1.0.0")
    git(repo, "checkout", "-q", "-b", "feature")
    return repo
