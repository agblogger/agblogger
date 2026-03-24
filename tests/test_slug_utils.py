"""Tests for slug utility functions."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.utils.slug import (
    CanonicalPostPath,
    file_path_to_slug,
    is_directory_post_path,
    resolve_slug_candidates,
    validated_post_path,
)


class TestIsDirectoryPostPath:
    """Tests for is_directory_post_path security-gate function."""

    def test_canonical_directory_post(self) -> None:
        assert is_directory_post_path("posts/hello/index.md") is True

    def test_nested_directory_post(self) -> None:
        assert is_directory_post_path("posts/2026/recap/index.md") is True

    def test_rejects_flat_file(self) -> None:
        assert is_directory_post_path("posts/hello.md") is False

    def test_rejects_trailing_slash_no_index(self) -> None:
        assert is_directory_post_path("posts/hello/") is False

    def test_rejects_missing_posts_prefix(self) -> None:
        assert is_directory_post_path("hello/index.md") is False

    def test_rejects_only_two_parts(self) -> None:
        assert is_directory_post_path("posts/index.md") is False

    def test_strips_leading_slash(self) -> None:
        assert is_directory_post_path("/posts/hello/index.md") is True

    def test_strips_whitespace(self) -> None:
        assert is_directory_post_path("  posts/hello/index.md  ") is True

    def test_rejects_empty_string(self) -> None:
        assert is_directory_post_path("") is False

    def test_rejects_whitespace_only(self) -> None:
        assert is_directory_post_path("   ") is False


class TestCanonicalPostPath:
    """Tests for the CanonicalPostPath NewType and validated_post_path constructor."""

    def test_valid_path_returns_canonical_post_path(self) -> None:
        result = validated_post_path("posts/hello/index.md")
        assert result == "posts/hello/index.md"

    def test_return_type_is_str(self) -> None:
        result = validated_post_path("posts/hello/index.md")
        assert isinstance(result, str)

    def test_rejects_flat_file(self) -> None:
        with pytest.raises(ValueError, match="Not a canonical post path"):
            validated_post_path("posts/hello.md")

    def test_rejects_non_post_path(self) -> None:
        with pytest.raises(ValueError, match="Not a canonical post path"):
            validated_post_path("hello/index.md")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Not a canonical post path"):
            validated_post_path("")

    def test_nested_path(self) -> None:
        result = validated_post_path("posts/2026/recap/index.md")
        assert result == "posts/2026/recap/index.md"

    def test_normalizes_leading_slash(self) -> None:
        result = validated_post_path("/posts/hello/index.md")
        assert result == "posts/hello/index.md"

    def test_normalizes_whitespace(self) -> None:
        result = validated_post_path("  posts/hello/index.md  ")
        assert result == "posts/hello/index.md"

    def test_newtype_is_assignable_to_str(self) -> None:
        path: CanonicalPostPath = validated_post_path("posts/hello/index.md")
        s: str = path
        assert s == "posts/hello/index.md"


class TestFilePathToSlugPropertyBased:
    """Property-based tests for file_path_to_slug using Hypothesis."""

    _slug_alphabet = st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="-",
    )

    @given(
        st.text(alphabet=_slug_alphabet, min_size=1).filter(
            lambda s: "/" not in s and not s.startswith("posts/")
        )
    )
    def test_idempotency_bare_slug(self, slug: str) -> None:
        """Bare slugs (no posts/ prefix) pass through unchanged."""
        assert file_path_to_slug(slug) == slug

    @given(st.text(alphabet=_slug_alphabet, min_size=1).filter(lambda s: "/" not in s and s))
    def test_roundtrip_directory_post(self, slug: str) -> None:
        """Canonical path roundtrips back to the original slug."""
        path = f"posts/{slug}/index.md"
        assert file_path_to_slug(path) == slug

    @given(st.text(alphabet=_slug_alphabet, min_size=1).filter(lambda s: "/" not in s and s))
    def test_no_slash_in_output_for_single_segment(self, slug: str) -> None:
        """Output never contains '/' for single-segment slugs."""
        result = file_path_to_slug(f"posts/{slug}/index.md")
        assert "/" not in result

    @given(st.text(alphabet=_slug_alphabet, min_size=1).filter(lambda s: "/" not in s and s))
    def test_flat_file_always_raises(self, slug: str) -> None:
        """Flat posts/slug.md paths always raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported post path"):
            file_path_to_slug(f"posts/{slug}.md")


class TestFilePathToSlug:
    """Tests for file_path_to_slug conversion."""

    def test_directory_backed_post(self) -> None:
        assert file_path_to_slug("posts/my-post/index.md") == "my-post"

    def test_rejects_legacy_flat_file_post(self) -> None:
        with pytest.raises(ValueError, match="Unsupported post path"):
            file_path_to_slug("posts/hello.md")

    def test_bare_slug_is_idempotent(self) -> None:
        assert file_path_to_slug("my-post") == "my-post"

    def test_rejects_directory_without_index_file(self) -> None:
        with pytest.raises(ValueError, match="Unsupported post path"):
            file_path_to_slug("posts/my-post/")

    def test_slug_with_hyphens(self) -> None:
        assert file_path_to_slug("posts/my-long-post-title/index.md") == "my-long-post-title"

    def test_rejects_flat_file_with_hyphens(self) -> None:
        with pytest.raises(ValueError, match="Unsupported post path"):
            file_path_to_slug("posts/another-post.md")

    def test_bare_slug_with_hyphens_is_idempotent(self) -> None:
        assert file_path_to_slug("some-bare-slug") == "some-bare-slug"

    def test_directory_backed_does_not_keep_index(self) -> None:
        """Regression: must strip /index.md entirely, not leave 'my-post/index'."""
        result = file_path_to_slug("posts/my-post/index.md")
        assert "/" not in result
        assert "index" not in result


class TestFilePathToSlugRegressions:
    """Regression tests covering bugs found in crosspost and symlink resolution."""

    def test_directory_backed_post_does_not_produce_index_in_slug(self) -> None:
        """Regression: crosspost_service was producing 'my-post/index' instead of 'my-post'.

        Old code stripped posts/ prefix and .md suffix but did NOT handle /index.md,
        leaving a slash in the slug which breaks crosspost URLs.
        """
        result = file_path_to_slug("posts/my-post/index.md")
        assert result == "my-post"
        assert "index" not in result
        assert "/" not in result

    def test_crosspost_url_with_directory_backed_post(self) -> None:
        """The slug produced by file_path_to_slug matches what a crosspost URL needs."""
        site_url = "https://example.com"
        post_path = "posts/my-first-post/index.md"
        slug = file_path_to_slug(post_path)
        post_url = f"{site_url.rstrip('/')}/post/{slug}"
        assert post_url == "https://example.com/post/my-first-post"

    def test_legacy_flat_file_crosspost_url_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported post path"):
            file_path_to_slug("posts/hello.md")


class TestResolveSlugCandidates:
    """Tests for resolve_slug_candidates path expansion."""

    def test_returns_tuple_of_one_candidate(self) -> None:
        candidates = resolve_slug_candidates("my-post")
        assert len(candidates) == 1

    def test_directory_backed_candidate(self) -> None:
        candidates = resolve_slug_candidates("my-post")
        assert candidates[0] == "posts/my-post/index.md"

    def test_slug_with_hyphens(self) -> None:
        candidates = resolve_slug_candidates("hello-world")
        assert candidates == ("posts/hello-world/index.md",)

    def test_returns_tuple_type(self) -> None:
        result = resolve_slug_candidates("my-post")
        assert isinstance(result, tuple)
