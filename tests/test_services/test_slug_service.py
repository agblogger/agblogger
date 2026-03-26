"""Tests for slug generation and post path generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services.slug_service import generate_post_path, generate_post_slug

FIXED_UTC = datetime(2026, 3, 15, 1, 0, 0, tzinfo=UTC)
"""A time where the UTC date (Mar 15) differs from UTC+10 local date (Mar 16)."""


class TestGeneratePostSlug:
    def test_basic_title(self) -> None:
        assert generate_post_slug("Hello World") == "hello-world"

    def test_lowercase(self) -> None:
        assert generate_post_slug("My GREAT Post") == "my-great-post"

    def test_strips_whitespace(self) -> None:
        assert generate_post_slug("  hello world  ") == "hello-world"

    def test_special_characters_replaced(self) -> None:
        assert generate_post_slug("Hello, World! How's it?") == "hello-world-how-s-it"

    def test_multiple_hyphens_collapsed(self) -> None:
        assert generate_post_slug("hello---world") == "hello-world"

    def test_mixed_special_chars_collapsed(self) -> None:
        assert generate_post_slug("hello & world @ 2026") == "hello-world-2026"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert generate_post_slug("---hello world---") == "hello-world"

    def test_unicode_normalized_to_ascii(self) -> None:
        assert generate_post_slug("cafe\u0301") == "cafe"

    def test_unicode_accented_chars(self) -> None:
        assert generate_post_slug("\u00e9t\u00e9 fran\u00e7ais") == "ete-francais"

    def test_unicode_german(self) -> None:
        assert generate_post_slug("\u00fcber cool") == "uber-cool"

    def test_empty_string_returns_untitled(self) -> None:
        assert generate_post_slug("") == "untitled"

    def test_whitespace_only_returns_untitled(self) -> None:
        assert generate_post_slug("   ") == "untitled"

    def test_special_chars_only_returns_untitled(self) -> None:
        assert generate_post_slug("!!!@@@###") == "untitled"

    def test_literal_untitled_title_does_not_use_fallback_slug(self) -> None:
        assert generate_post_slug("Untitled") == "untitled-post"

    def test_long_title_truncated_to_80_chars(self) -> None:
        title = "this is a very long title " * 10
        slug = generate_post_slug(title)
        assert len(slug) <= 80

    def test_long_title_does_not_cut_mid_word(self) -> None:
        # Build a title that would be cut mid-word at exactly 80 chars
        title = "short " * 20  # "short-short-short-..." each word is 5 chars + hyphen
        slug = generate_post_slug(title)
        assert len(slug) <= 80
        assert not slug.endswith("-")

    def test_long_title_no_trailing_hyphen(self) -> None:
        title = "a" * 100
        slug = generate_post_slug(title)
        assert len(slug) <= 80
        assert not slug.endswith("-")

    def test_single_long_word_truncated(self) -> None:
        title = "a" * 100
        slug = generate_post_slug(title)
        assert len(slug) <= 80
        # A single word that exceeds 80 chars must be hard-truncated
        assert slug == "a" * 80

    def test_numbers_preserved(self) -> None:
        assert generate_post_slug("Python 3.13 Release") == "python-3-13-release"

    def test_hyphens_in_input_preserved(self) -> None:
        assert generate_post_slug("state-of-the-art") == "state-of-the-art"

    def test_tabs_and_newlines_handled(self) -> None:
        assert generate_post_slug("hello\tworld\nnew") == "hello-world-new"


class TestGeneratePostPath:
    def test_basic_path_generation(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        result = generate_post_path("Hello World", posts_dir)
        # Should be posts_dir / "YYYY-MM-DD-hello-world" / "index.md"
        assert result.name == "index.md"
        assert result.parent.parent == posts_dir
        dir_name = result.parent.name
        assert dir_name.endswith("-hello-world")
        # Should start with a date prefix
        parts = dir_name.split("-", 3)
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day

    def test_path_uses_utc_date(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        with patch("backend.services.slug_service.now_utc", return_value=FIXED_UTC):
            result = generate_post_path("Test Post", posts_dir)
        dir_name = result.parent.name
        assert dir_name.startswith("2026-03-15")

    def test_collision_appends_suffix(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        # Create the first path and make its directory
        first = generate_post_path("My Post", posts_dir)
        first.parent.mkdir(parents=True)
        # Generate again — should get -2 suffix
        second = generate_post_path("My Post", posts_dir)
        assert second != first
        assert second.parent.name.endswith("-2")
        assert second.name == "index.md"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        # Create first and second
        first = generate_post_path("My Post", posts_dir)
        first.parent.mkdir(parents=True)
        second = generate_post_path("My Post", posts_dir)
        second.parent.mkdir(parents=True)
        # Third should get -3
        third = generate_post_path("My Post", posts_dir)
        assert third.parent.name.endswith("-3")
        assert third.name == "index.md"

    def test_empty_title_uses_untitled(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        result = generate_post_path("", posts_dir)
        assert "untitled" in result.parent.name

    def test_returns_path_object(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        result = generate_post_path("Test", posts_dir)
        assert isinstance(result, Path)


class TestSlugCollisionCap:
    def test_raises_after_1000_collisions(self, tmp_path: Path) -> None:
        """generate_post_path must raise ValueError after 1000 collisions."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        slug = generate_post_slug("My Post")
        today = "2026-03-15"
        (posts_dir / f"{today}-{slug}").mkdir()
        for i in range(2, 1001):
            (posts_dir / f"{today}-{slug}-{i}").mkdir()
        with (
            patch("backend.services.slug_service.now_utc", return_value=FIXED_UTC),
            pytest.raises(ValueError, match="Too many slug collisions"),
        ):
            generate_post_path("My Post", posts_dir)

    def test_finds_slot_just_before_cap(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        slug = generate_post_slug("My Post")
        today = "2026-03-15"
        (posts_dir / f"{today}-{slug}").mkdir()
        for i in range(2, 1000):
            (posts_dir / f"{today}-{slug}-{i}").mkdir()
        with patch("backend.services.slug_service.now_utc", return_value=FIXED_UTC):
            result = generate_post_path("My Post", posts_dir)
        assert result.parent.name == f"{today}-{slug}-1000"
