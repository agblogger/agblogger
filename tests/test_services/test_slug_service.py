"""Tests for slug generation and post path generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.services.slug_service import (
    _is_available_directory,
    date_slug_prefix,
    generate_post_path,
    generate_post_slug,
)

_DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-$")


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
        assert result.name == "index.md"
        assert result.parent.parent == posts_dir
        assert result.parent.name == "hello-world"

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
        (posts_dir / slug).mkdir()
        for i in range(2, 1001):
            (posts_dir / f"{slug}-{i}").mkdir()
        with pytest.raises(ValueError, match="Too many slug collisions"):
            generate_post_path("My Post", posts_dir)

    def test_finds_slot_just_before_cap(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        slug = generate_post_slug("My Post")
        (posts_dir / slug).mkdir()
        for i in range(2, 1000):
            (posts_dir / f"{slug}-{i}").mkdir()
        result = generate_post_path("My Post", posts_dir)
        assert result.parent.name == f"{slug}-1000"


class TestDateSlugPrefix:
    """Example-based tests for date_slug_prefix."""

    def test_valid_date_prefix_returns_prefix(self) -> None:
        assert date_slug_prefix("2026-03-28-my-post") == "2026-03-28-"

    def test_no_date_prefix_returns_empty(self) -> None:
        assert date_slug_prefix("my-post") == ""

    def test_just_date_prefix_returns_prefix(self) -> None:
        assert date_slug_prefix("2026-03-28-") == "2026-03-28-"

    def test_partial_date_missing_day_returns_empty(self) -> None:
        assert date_slug_prefix("2026-03-my-post") == ""

    def test_empty_string_returns_empty(self) -> None:
        assert date_slug_prefix("") == ""

    def test_date_with_slug_suffix(self) -> None:
        assert date_slug_prefix("2000-01-01-hello-world") == "2000-01-01-"

    def test_date_only_no_trailing_hyphen_returns_empty(self) -> None:
        assert date_slug_prefix("2026-03-28") == ""

    def test_non_numeric_year_returns_empty(self) -> None:
        assert date_slug_prefix("abcd-03-28-my-post") == ""

    def test_leading_spaces_return_empty(self) -> None:
        assert date_slug_prefix(" 2026-03-28-my-post") == ""


class TestDateSlugPrefixPropertyBased:
    """Property-based tests for date_slug_prefix."""

    @given(
        year=st.integers(min_value=1000, max_value=9999),
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28),
        suffix=st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-"),
            min_size=0,
            max_size=50,
        ),
    )
    def test_valid_date_prefix_string_returns_prefix(
        self, year: int, month: int, day: int, suffix: str
    ) -> None:
        """For any string of form YYYY-MM-DD-{suffix}, the function returns the date prefix."""
        directory_name = f"{year:04d}-{month:02d}-{day:02d}-{suffix}"
        result = date_slug_prefix(directory_name)
        expected_prefix = f"{year:04d}-{month:02d}-{day:02d}-"
        assert result == expected_prefix

    @given(st.text())
    @settings(max_examples=500)
    def test_result_is_always_empty_or_matches_date_pattern(self, directory_name: str) -> None:
        """The return value is always either '' or matches the \\d{4}-\\d{2}-\\d{2}- pattern."""
        result = date_slug_prefix(directory_name)
        assert result == "" or bool(_DATE_PREFIX_PATTERN.match(result))

    @given(
        year=st.integers(min_value=1000, max_value=9999),
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28),
    )
    def test_idempotent_composition(self, year: int, month: int, day: int) -> None:
        """date_slug_prefix is idempotent when composed: prefix extracted from a string
        that starts with a date prefix is the same prefix."""
        original = f"{year:04d}-{month:02d}-{day:02d}-rest"
        prefix = date_slug_prefix(original)
        assert prefix != ""
        composed = f"{prefix}rest"
        assert date_slug_prefix(composed) == prefix

    @given(st.text())
    def test_result_length_is_zero_or_eleven(self, directory_name: str) -> None:
        """The return value is either '' (len 0) or exactly 11 chars 'YYYY-MM-DD-'."""
        result = date_slug_prefix(directory_name)
        assert len(result) == 0 or len(result) == 11

    @given(st.text())
    def test_no_trailing_content_when_nonempty(self, directory_name: str) -> None:
        """When a prefix is returned, it always ends with a hyphen."""
        result = date_slug_prefix(directory_name)
        if result:
            assert result.endswith("-")


class TestIsAvailableDirectory:
    """Example-based tests for _is_available_directory."""

    def test_candidate_matches_current_dir_is_available(self, tmp_path: Path) -> None:
        """When candidate == current_dir, it is available (reuse case)."""
        existing = tmp_path / "2026-03-28-my-post"
        existing.mkdir()
        assert _is_available_directory(existing, existing) is True

    def test_nonexistent_candidate_is_available(self, tmp_path: Path) -> None:
        """When candidate doesn't exist, it is available."""
        candidate = tmp_path / "2026-03-28-new-post"
        assert _is_available_directory(candidate, None) is True

    def test_existing_candidate_not_current_dir_is_not_available(self, tmp_path: Path) -> None:
        """When candidate exists and doesn't match current_dir, it is not available."""
        candidate = tmp_path / "2026-03-28-existing-post"
        candidate.mkdir()
        current = tmp_path / "2026-03-28-other-post"
        assert _is_available_directory(candidate, current) is False

    def test_existing_candidate_with_none_current_dir_is_not_available(
        self, tmp_path: Path
    ) -> None:
        """When candidate exists and current_dir is None, it is not available."""
        candidate = tmp_path / "2026-03-28-existing-post"
        candidate.mkdir()
        assert _is_available_directory(candidate, None) is False

    def test_nonexistent_candidate_with_different_current_dir_is_available(
        self, tmp_path: Path
    ) -> None:
        """A non-existent candidate is always available, regardless of current_dir."""
        candidate = tmp_path / "2026-03-28-new-post"
        current = tmp_path / "2026-03-28-old-post"
        assert _is_available_directory(candidate, current) is True
