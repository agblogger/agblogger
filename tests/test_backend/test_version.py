from __future__ import annotations

from typing import TYPE_CHECKING

from backend.version import _resolve_version

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_version_with_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "BUILD").write_text("abc1234\n")
    assert _resolve_version(tmp_path) == "1.2.3+abc1234"


def test_resolve_version_without_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert _resolve_version(tmp_path) == "1.2.3"


def test_resolve_version_empty_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "BUILD").write_text("\n")
    assert _resolve_version(tmp_path) == "1.2.3"


def test_get_version_returns_string() -> None:
    from backend.version import get_version

    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0
