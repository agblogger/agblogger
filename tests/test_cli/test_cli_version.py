from __future__ import annotations

from pathlib import Path

from cli.version import get_cli_version


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
