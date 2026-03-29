from __future__ import annotations

import contextlib
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

from cli.version import get_cli_version

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_version_with_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    (tmp_path / "BUILD").write_text("def5678\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    # Clear the lru_cache so the monkeypatch takes effect
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0+def5678"
    get_cli_version.cache_clear()


def test_cli_version_without_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0"
    get_cli_version.cache_clear()


def test_cli_version_empty_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    (tmp_path / "BUILD").write_text("\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0"
    get_cli_version.cache_clear()


def test_cli_version_no_version_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "unknown"
    get_cli_version.cache_clear()


def test_cli_version_unreadable_version_file(tmp_path: Path, monkeypatch) -> None:
    """Unreadable VERSION file should return 'unknown'."""
    (tmp_path / "VERSION").write_text("2.0.0\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    with patch.object(
        type(tmp_path / "VERSION"),
        "read_text",
        side_effect=OSError("permission denied"),
    ):
        assert get_cli_version() == "unknown"
    get_cli_version.cache_clear()


def test_cli_version_unreadable_build_file(tmp_path: Path, monkeypatch) -> None:
    """Unreadable BUILD file should fall back to base version."""
    (tmp_path / "VERSION").write_text("2.0.0\n")
    build = tmp_path / "BUILD"
    build.write_text("def5678\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    original = type(build).read_text

    def fail_on_build(self, *args, **kwargs):
        if self.name == "BUILD":
            raise OSError("disk error")
        return original(self, *args, **kwargs)

    with patch.object(type(build), "read_text", fail_on_build):
        assert get_cli_version() == "2.0.0"
    get_cli_version.cache_clear()


def test_cli_version_flag_prints_version(capsys, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("3.0.0\n")
    (tmp_path / "BUILD").write_text("cafe123\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()

    from cli.sync_client import main

    monkeypatch.setattr(sys, "argv", ["agblogger", "--version"])
    with contextlib.suppress(SystemExit):
        main()
    captured = capsys.readouterr()
    assert "3.0.0+cafe123" in captured.out
    get_cli_version.cache_clear()
