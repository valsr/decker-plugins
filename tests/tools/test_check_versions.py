import json
from pathlib import Path

from assertpy import assert_that

from tools.check_versions import check_versions

from .conftest import git


def _bump(repo: Path, version: str) -> None:
    manifest = repo / "plugins" / "com.example.demo" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    manifest.write_text(json.dumps(data), encoding="utf-8")


def _commit_change(repo: Path) -> None:
    (repo / "plugins" / "com.example.demo" / "pack" / "a.png").write_bytes(b"changed")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")


def test_check_versions_flags_unbumped_change(git_repo: Path) -> None:
    _commit_change(git_repo)

    errors = check_versions(git_repo, "main")

    assert_that(errors).is_length(1)
    assert_that(errors[0]).contains("com.example.demo").contains("1.0.0")


def test_check_versions_passes_bumped(git_repo: Path) -> None:
    _commit_change(git_repo)
    _bump(git_repo, "1.0.1")
    git(git_repo, "commit", "-q", "-am", "bump")

    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_passes_unchanged_plugin(git_repo: Path) -> None:
    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_new_plugin_without_tag_passes(git_repo: Path) -> None:
    from .conftest import write_plugin

    write_plugin(git_repo / "plugins", "com.example.other", "0.1.0")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "new plugin")

    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_rejects_invalid_semver(git_repo: Path) -> None:
    _bump(git_repo, "banana")
    git(git_repo, "commit", "-q", "-am", "bad")

    errors = check_versions(git_repo, "main")

    assert_that(errors).is_length(1)
    assert_that(errors[0]).contains("banana")


def test_check_versions_compares_numerically(git_repo: Path) -> None:
    git(git_repo, "tag", "com.example.demo-v1.9.0")
    _bump(git_repo, "1.10.0")
    git(git_repo, "commit", "-q", "-am", "bump")

    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_rejects_semver_that_packaging_cannot_parse(git_repo: Path) -> None:
    _bump(git_repo, "1.0.0-foo")
    git(git_repo, "commit", "-q", "-am", "bad")

    errors = check_versions(git_repo, "main")

    assert_that(errors).is_length(1)
    assert_that(errors[0]).contains("1.0.0-foo").contains("PEP 440")


def test_check_versions_ignores_unparseable_tags(git_repo: Path) -> None:
    git(git_repo, "tag", "com.example.demo-v1.0.0-foo")
    _bump(git_repo, "1.0.1")
    git(git_repo, "commit", "-q", "-am", "bump")

    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_ignores_changes_under_tests(git_repo: Path) -> None:
    tests_dir = git_repo / "plugins" / "com.example.demo" / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "tests only")

    assert_that(check_versions(git_repo, "main")).is_empty()


def test_check_versions_still_flags_tests_plus_packaged_change(git_repo: Path) -> None:
    tests_dir = git_repo / "plugins" / "com.example.demo" / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    _commit_change(git_repo)

    assert_that(check_versions(git_repo, "main")).is_length(1)


def test_check_versions_on_push_compares_with_previous_commit(git_repo: Path) -> None:
    git(git_repo, "checkout", "-q", "main")
    git(git_repo, "merge", "-q", "--ff-only", "HEAD")
    previous = git(git_repo, "rev-parse", "HEAD").strip()
    _commit_change(git_repo)

    errors = check_versions(git_repo, previous)

    assert_that(errors).is_length(1)
    assert_that(errors[0]).contains("com.example.demo")


def test_check_versions_ignores_the_release_tag_on_head(git_repo: Path) -> None:
    _commit_change(git_repo)
    _bump(git_repo, "1.0.1")
    git(git_repo, "commit", "-q", "-am", "bump")
    git(git_repo, "tag", "com.example.demo-v1.0.1")  # publish already released this commit

    assert_that(check_versions(git_repo, "main")).is_empty()
