from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

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


def test_resolve_version_build_read_error(tmp_path: Path) -> None:
    """OSError reading BUILD should fall back to base version."""
    (tmp_path / "VERSION").write_text("1.2.3\n")
    build = tmp_path / "BUILD"
    build.write_text("abc1234\n")
    original = type(build).read_text

    def fail_on_build(self, *args, **kwargs):
        if self.name == "BUILD":
            raise OSError("disk error")
        return original(self, *args, **kwargs)

    with patch.object(type(build), "read_text", fail_on_build):
        assert _resolve_version(tmp_path) == "1.2.3"


def test_resolve_version_build_unicode_error(tmp_path: Path) -> None:
    """UnicodeDecodeError reading BUILD should fall back to base version."""
    (tmp_path / "VERSION").write_text("1.2.3\n")
    build = tmp_path / "BUILD"
    build.write_text("abc1234\n")
    original = type(build).read_text

    def fail_on_build(self, *args, **kwargs):
        if self.name == "BUILD":
            raise UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalid")
        return original(self, *args, **kwargs)

    with patch.object(type(build), "read_text", fail_on_build):
        assert _resolve_version(tmp_path) == "1.2.3"


def test_get_version_returns_string() -> None:
    from backend.version import get_version

    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0
