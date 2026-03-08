"""Tests for the release workflow."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from cli.release import (
    ReleaseError,
    bump_version,
    read_repo_version,
    run_release,
    update_version_files,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def _write_release_fixture(root: Path) -> None:
    (root / "packaging" / "server").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend").mkdir()

    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")

    (root / "pyproject.toml").write_text(
        '[project]\nname = "agblogger"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "packaging" / "server" / "pyproject.toml").write_text(
        '[project]\nname = "agblogger-server"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "agblogger"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "frontend" / "package.json").write_text(
        json.dumps({"name": "agblogger-frontend", "version": "0.1.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "agblogger-frontend",
                "version": "0.1.0",
                "packages": {"": {"name": "agblogger-frontend", "version": "0.1.0"}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_bump_version_supports_patch_minor_and_major() -> None:
    assert bump_version("0.1.0", "patch") == "0.1.1"
    assert bump_version("0.1.0", "minor") == "0.2.0"
    assert bump_version("0.1.0", "major") == "1.0.0"


def test_bump_version_rejects_invalid_version_shape() -> None:
    with pytest.raises(ReleaseError, match="semantic version"):
        bump_version("0.1", "patch")


def test_read_repo_version_reads_version_file(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path)

    assert read_repo_version(tmp_path) == "0.1.0"


def test_update_version_files_updates_all_release_surfaces(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path)

    updated_paths = update_version_files(tmp_path, "0.1.0", "0.1.1")

    assert sorted(path.as_posix() for path in updated_paths) == [
        "VERSION",
        "frontend/package-lock.json",
        "frontend/package.json",
        "packaging/server/pyproject.toml",
        "pyproject.toml",
        "uv.lock",
    ]
    for rel_path in updated_paths:
        content = (tmp_path / rel_path).read_text(encoding="utf-8")
        assert "0.1.1" in content
        assert "0.1.0" not in content


def test_update_version_files_rejects_unexpected_current_version(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path)
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        '[project]\nname = "agblogger"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(ReleaseError, match=r"Expected current version 0\.1\.0"):
        update_version_files(tmp_path, "0.1.0", "0.1.1")


def test_run_release_updates_versions_and_invokes_git_and_github(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _write_release_fixture(tmp_path)
    commands: list[tuple[list[str], Path]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> SimpleNamespace:
        del check, text
        commands.append((command, cwd))
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command == ["git", "rev-parse", "--verify", "refs/tags/v0.1.1"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if command == ["gh", "release", "view", "v0.1.1"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if capture_output:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.release.subprocess.run", fake_run)
    monkeypatch.setattr("cli.release.shutil.which", lambda _name: f"/usr/bin/{_name}")

    result = run_release(tmp_path, "patch")

    assert result.old_version == "0.1.0"
    assert result.new_version == "0.1.1"
    assert result.tag == "v0.1.1"
    assert result.tarball_path == tmp_path / "dist" / "releases" / "agblogger-0.1.1.tar.gz"
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "0.1.1\n"
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8").count("0.1.1") == 1
    assert commands == [
        (["git", "status", "--short"], tmp_path),
        (["git", "rev-parse", "--verify", "refs/tags/v0.1.1"], tmp_path),
        (["gh", "release", "view", "v0.1.1"], tmp_path),
        (
            [
                "git",
                "add",
                "VERSION",
                "pyproject.toml",
                "packaging/server/pyproject.toml",
                "frontend/package.json",
                "frontend/package-lock.json",
                "uv.lock",
            ],
            tmp_path,
        ),
        (["git", "commit", "-m", "release: v0.1.1"], tmp_path),
        (["git", "tag", "-a", "v0.1.1", "-m", "Release v0.1.1"], tmp_path),
        (
            [
                "git",
                "archive",
                "--format=tar.gz",
                "--prefix=agblogger-0.1.1/",
                "-o",
                str(tmp_path / "dist" / "releases" / "agblogger-0.1.1.tar.gz"),
                "v0.1.1",
            ],
            tmp_path,
        ),
        (["git", "push", "origin", "HEAD"], tmp_path),
        (["git", "push", "origin", "v0.1.1"], tmp_path),
        (
            [
                "gh",
                "release",
                "create",
                "v0.1.1",
                str(tmp_path / "dist" / "releases" / "agblogger-0.1.1.tar.gz"),
                "--title",
                "v0.1.1",
                "--generate-notes",
            ],
            tmp_path,
        ),
    ]


def test_run_release_rejects_dirty_worktree(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _write_release_fixture(tmp_path)

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> SimpleNamespace:
        del cwd, check, capture_output, text
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(returncode=0, stdout=" M pyproject.toml\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("cli.release.subprocess.run", fake_run)
    monkeypatch.setattr("cli.release.shutil.which", lambda _name: f"/usr/bin/{_name}")

    with pytest.raises(ReleaseError, match="clean git worktree"):
        run_release(tmp_path, "patch")


def test_justfile_exposes_release_recipe() -> None:
    justfile = Path(__file__).resolve().parents[2] / "justfile"
    content = justfile.read_text(encoding="utf-8")

    assert 'release level:\n    uv run agblogger-release "{{ level }}"' in content
