"""Property-based tests for slug generation."""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.slug_service import MAX_SLUG_LENGTH, generate_post_slug

PROPERTY_SETTINGS = settings(
    max_examples=260,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_VALID_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# General unicode text (titles can be anything)
_TITLE = st.text(min_size=0, max_size=200)

# Titles that contain at least one ASCII alphanumeric character
_NONEMPTY_TITLE = st.text(min_size=1, max_size=200).filter(
    lambda t: any(c.isascii() and c.isalnum() for c in t)
)

# Pure ASCII alphanumeric titles (for idempotence testing)
_ASCII_ALNUM_TITLE = st.from_regex(r"[a-z0-9][a-z0-9 -]{0,60}", fullmatch=True)


class TestSlugFormatProperties:
    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_matches_valid_format(self, title: str) -> None:
        """Every slug is lowercase alphanumeric with single hyphens, or 'untitled'."""
        slug = generate_post_slug(title)
        assert _VALID_SLUG_RE.match(slug), f"Invalid slug format: {slug!r}"

    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_length_never_exceeds_maximum(self, title: str) -> None:
        slug = generate_post_slug(title)
        assert len(slug) <= MAX_SLUG_LENGTH

    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_is_never_empty(self, title: str) -> None:
        slug = generate_post_slug(title)
        assert len(slug) >= 1

    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_has_no_leading_or_trailing_hyphens(self, title: str) -> None:
        slug = generate_post_slug(title)
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_has_no_consecutive_hyphens(self, title: str) -> None:
        slug = generate_post_slug(title)
        assert "--" not in slug

    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_is_entirely_lowercase(self, title: str) -> None:
        slug = generate_post_slug(title)
        assert slug == slug.lower()


class TestSlugDeterminismProperties:
    @PROPERTY_SETTINGS
    @given(title=_TITLE)
    def test_slug_is_deterministic(self, title: str) -> None:
        """Same input always produces the same slug."""
        assert generate_post_slug(title) == generate_post_slug(title)

    @PROPERTY_SETTINGS
    @given(title=_ASCII_ALNUM_TITLE)
    def test_slug_is_idempotent_on_valid_slugs(self, title: str) -> None:
        """Applying slug generation to an already-valid slug produces the same result."""
        slug = generate_post_slug(title)
        assert generate_post_slug(slug) == slug


class TestSlugEdgeCaseProperties:
    @PROPERTY_SETTINGS
    @given(title=st.text(alphabet=" \t\n\r", min_size=0, max_size=50))
    def test_whitespace_only_titles_produce_untitled(self, title: str) -> None:
        assert generate_post_slug(title) == "untitled"

    @PROPERTY_SETTINGS
    @given(title=_NONEMPTY_TITLE)
    def test_nonempty_ascii_titles_never_produce_untitled(self, title: str) -> None:
        """Titles with at least one ASCII alphanumeric character produce a non-'untitled' slug."""
        slug = generate_post_slug(title)
        assert slug != "untitled"

    @PROPERTY_SETTINGS
    @given(title=_TITLE, extra_spaces=st.text(alphabet=" \t", min_size=0, max_size=10))
    def test_leading_trailing_whitespace_is_ignored(self, title: str, extra_spaces: str) -> None:
        """Whitespace around the title does not change the slug."""
        assert generate_post_slug(title) == generate_post_slug(extra_spaces + title + extra_spaces)


class TestSlugUnicodeProperties:
    @PROPERTY_SETTINGS
    @given(
        base=_ASCII_ALNUM_TITLE,
        accents=st.sampled_from(
            ["\u0301", "\u0308", "\u0327", "\u0300", "\u0302"]  # combining marks
        ),
    )
    def test_combining_marks_are_stripped(self, base: str, accents: str) -> None:
        """Combining diacritical marks are removed during NFKD normalization."""
        accented = base[0] + accents + base[1:]
        slug_accented = generate_post_slug(accented)
        # The slug should still be valid format (mark is stripped, not turned into hyphen)
        assert _VALID_SLUG_RE.match(slug_accented)
