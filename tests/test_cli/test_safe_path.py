"""Tests for _is_safe_local_path security boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cli.sync_client import _is_safe_local_path

if TYPE_CHECKING:
    from pathlib import Path


class TestIsSafeLocalPath:
    def test_normal_path_resolves(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/hello.md")
        assert result is not None
        assert result == (tmp_path / "posts" / "hello.md").resolve()

    def test_traversal_returns_none(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "../../etc/passwd")
        assert result is None

    def test_absolute_traversal_returns_none(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "../../etc/passwd")
        assert result is None
        result = _is_safe_local_path(tmp_path, "../../../etc/passwd")
        assert result is None

    def test_dotdot_in_middle_returns_none(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/../../../etc/passwd")
        assert result is None

    def test_nested_path_resolves(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/cooking/recipe.md")
        assert result is not None
        assert str(result).endswith("posts/cooking/recipe.md")

    def test_null_byte_in_path_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="null"):
            _is_safe_local_path(tmp_path, "posts/\x00../etc/passwd")

    def test_url_encoded_traversal_treated_as_literal(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/%2e%2e/etc/passwd")
        assert result is not None
        assert result.is_relative_to(tmp_path.resolve())

    def test_double_encoded_traversal_treated_as_literal(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/%252e%252e/etc/passwd")
        assert result is not None
        assert result.is_relative_to(tmp_path.resolve())

    def test_very_long_path_resolves(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts/" + "a" * 1000 + ".md")
        assert result is not None
        assert result.is_relative_to(tmp_path.resolve())

    def test_backslash_traversal_stays_within_root(self, tmp_path: Path):
        result = _is_safe_local_path(tmp_path, "posts\\..\\..\\etc\\passwd")
        assert result is not None
        assert result.is_relative_to(tmp_path.resolve())
