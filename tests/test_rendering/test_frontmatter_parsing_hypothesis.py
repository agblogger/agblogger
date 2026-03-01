"""Property-based tests for frontmatter parsing and serialization."""

from __future__ import annotations

import string
from datetime import UTC, datetime

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from backend.filesystem.frontmatter import (
    extract_title,
    generate_markdown_excerpt,
    parse_labels,
    parse_post,
    serialize_post,
    strip_leading_heading,
)

PROPERTY_SETTINGS = settings(
    max_examples=220,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# --- Strategies ---

# Titles must start with an alphanumeric character to be YAML-safe
# (titles like "-" or "- foo" are ambiguous in YAML block context)
_SAFE_TITLE = (
    st.text(
        alphabet=string.ascii_letters + string.digits + " -_",
        min_size=2,
        max_size=60,
    )
    .map(str.strip)
    .filter(lambda s: len(s) >= 2 and s[0].isalnum())
)

_LABEL_ID = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-",
    min_size=1,
    max_size=12,
).filter(lambda s: s[0].isalnum())

_LABEL_LIST = st.lists(_LABEL_ID, max_size=8)

_BODY_LINE = st.text(
    alphabet=string.ascii_letters + string.digits + " .,!?-_",
    min_size=0,
    max_size=80,
)

_BODY = st.lists(_BODY_LINE, min_size=0, max_size=15).map("\n".join)

_AWARE_DATETIME = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(UTC),
)


@st.composite
def _markdown_with_heading(draw: st.DrawFn) -> tuple[str, str]:
    """Generate markdown content with a leading heading and the expected title."""
    title = draw(_SAFE_TITLE)
    body = draw(_BODY)
    blank_lines = draw(st.integers(min_value=0, max_value=3))
    content = "\n" * blank_lines + f"# {title}\n\n{body}"
    return content, title


@st.composite
def _frontmatter_markdown(draw: st.DrawFn) -> str:
    """Generate valid markdown with YAML front matter."""
    title = draw(_SAFE_TITLE)
    created_at = draw(_AWARE_DATETIME)
    modified_at = draw(_AWARE_DATETIME)
    author_st = st.one_of(
        st.none(), st.text(alphabet=string.ascii_letters, min_size=1, max_size=20)
    )
    author = draw(author_st)
    labels = draw(_LABEL_LIST)
    body = draw(_BODY)

    parts = ["---"]
    parts.append(f"title: '{title}'")
    parts.append(f"created_at: {created_at.strftime('%Y-%m-%d %H:%M:%S.%f%z')}")
    parts.append(f"modified_at: {modified_at.strftime('%Y-%m-%d %H:%M:%S.%f%z')}")
    if author:
        parts.append(f"author: {author}")
    if labels:
        label_strs = ", ".join(f'"#{label}"' for label in labels)
        parts.append(f"labels: [{label_strs}]")
    parts.append("---")
    parts.append(body)
    return "\n".join(parts)


# --- Test Classes ---


class TestExtractTitleProperties:
    @PROPERTY_SETTINGS
    @given(data=_markdown_with_heading())
    def test_extracts_title_from_leading_heading(self, data: tuple[str, str]) -> None:
        """extract_title finds the first # heading and returns its text."""
        content, expected_title = data
        assert extract_title(content) == expected_title

    @PROPERTY_SETTINGS
    @given(body=_BODY)
    def test_returns_untitled_when_no_heading(self, body: str) -> None:
        """Content without any # heading returns 'Untitled' (no file_path)."""
        assume(not any(line.strip().startswith("# ") for line in body.split("\n")))
        assert extract_title(body) == "Untitled"

    @PROPERTY_SETTINGS
    @given(body=_BODY)
    def test_never_returns_empty_string(self, body: str) -> None:
        """extract_title never returns an empty string."""
        result = extract_title(body)
        assert len(result) >= 1

    @PROPERTY_SETTINGS
    @given(title=_SAFE_TITLE)
    def test_h2_headings_are_not_extracted(self, title: str) -> None:
        """## headings are not treated as titles."""
        content = f"## {title}\n\nSome body"
        assert extract_title(content) != title


class TestStripLeadingHeadingProperties:
    @PROPERTY_SETTINGS
    @given(title=_SAFE_TITLE, body=_BODY)
    def test_strips_matching_heading(self, title: str, body: str) -> None:
        """When first non-blank line is # title, it is removed."""
        content = f"# {title}\n{body}"
        result = strip_leading_heading(content, title)
        assert not result.lstrip("\n").startswith(f"# {title}")

    @PROPERTY_SETTINGS
    @given(title=_SAFE_TITLE, other_title=_SAFE_TITLE, body=_BODY)
    def test_preserves_non_matching_heading(self, title: str, other_title: str, body: str) -> None:
        """When heading does not match title, content is returned unchanged."""
        assume(title != other_title)
        content = f"# {other_title}\n{body}"
        assert strip_leading_heading(content, title) == content

    @PROPERTY_SETTINGS
    @given(body=_BODY)
    def test_no_heading_returns_content_unchanged(self, body: str) -> None:
        """Content without a leading heading is returned as-is."""
        assume(not any(line.strip().startswith("# ") for line in body.split("\n")[:5]))
        result = strip_leading_heading(body, "Any Title")
        assert result == body


class TestParseLabelsProperties:
    @PROPERTY_SETTINGS
    @given(labels=_LABEL_LIST)
    def test_hash_prefixed_labels_are_stripped(self, labels: list[str]) -> None:
        """Labels with # prefix have it removed."""
        prefixed = [f"#{label}" for label in labels]
        result = parse_labels(prefixed)
        assert result == labels

    @PROPERTY_SETTINGS
    @given(labels=_LABEL_LIST)
    def test_unprefixed_labels_pass_through(self, labels: list[str]) -> None:
        """Labels without # prefix are returned as-is."""
        result = parse_labels(labels)
        assert result == labels

    @PROPERTY_SETTINGS
    @given(labels=_LABEL_LIST)
    def test_hash_stripping_is_idempotent(self, labels: list[str]) -> None:
        """Parsing the output of parse_labels again returns the same result."""
        first = parse_labels(labels)
        second = parse_labels(first)
        assert first == second

    @PROPERTY_SETTINGS
    @given(value=st.one_of(st.none(), st.integers(), st.text(max_size=20)))
    def test_non_list_input_returns_empty(self, value: object) -> None:
        """Non-list inputs return an empty list."""
        if isinstance(value, list):
            return
        assert parse_labels(value) == []


class TestExcerptProperties:
    @PROPERTY_SETTINGS
    @given(content=_BODY, max_length=st.integers(min_value=10, max_value=500))
    def test_excerpt_length_within_bounds(self, content: str, max_length: int) -> None:
        """Excerpt length never exceeds max_length + len('...')."""
        result = generate_markdown_excerpt(content, max_length=max_length)
        # When truncation adds "..." it may overshoot by exactly 3 chars
        assert len(result) <= max_length + 3

    @PROPERTY_SETTINGS
    @given(content=_BODY)
    def test_excerpt_strips_headings(self, content: str) -> None:
        """Lines starting with # are removed from the excerpt."""
        result = generate_markdown_excerpt(content)
        for line in result.split("\n"):
            stripped = line.strip()
            if stripped:
                assert not stripped.startswith("#")

    @PROPERTY_SETTINGS
    @given(body=_BODY)
    def test_excerpt_strips_code_blocks(self, body: str) -> None:
        """Content inside ``` fences is excluded from the excerpt."""
        content = f"Some intro\n```\ncode line\n```\n{body}"
        result = generate_markdown_excerpt(content)
        assert "code line" not in result

    @PROPERTY_SETTINGS
    @given(content=_BODY)
    def test_excerpt_is_deterministic(self, content: str) -> None:
        assert generate_markdown_excerpt(content) == generate_markdown_excerpt(content)


class TestSerializeParseRoundtripProperties:
    @PROPERTY_SETTINGS
    @given(raw=_frontmatter_markdown())
    def test_parse_then_serialize_preserves_metadata(self, raw: str) -> None:
        """Parsing markdown and serializing it back preserves title, author, labels, draft."""
        parsed = parse_post(raw, default_tz="UTC", default_author="")
        serialized = serialize_post(parsed)
        reparsed = parse_post(serialized, default_tz="UTC", default_author="")

        assert reparsed.title == parsed.title
        assert reparsed.author == parsed.author
        assert sorted(reparsed.labels) == sorted(parsed.labels)
        assert reparsed.is_draft == parsed.is_draft

    @PROPERTY_SETTINGS
    @given(raw=_frontmatter_markdown())
    def test_roundtrip_preserves_timestamps(self, raw: str) -> None:
        """Parse → serialize → parse preserves created_at and modified_at."""
        parsed = parse_post(raw, default_tz="UTC", default_author="")
        serialized = serialize_post(parsed)
        reparsed = parse_post(serialized, default_tz="UTC", default_author="")

        assert abs((reparsed.created_at - parsed.created_at).total_seconds()) < 0.001
        assert abs((reparsed.modified_at - parsed.modified_at).total_seconds()) < 0.001

    @PROPERTY_SETTINGS
    @given(raw=_frontmatter_markdown())
    def test_serialized_output_has_frontmatter_delimiters(self, raw: str) -> None:
        """Serialized markdown starts with --- and contains a second ---."""
        parsed = parse_post(raw, default_tz="UTC", default_author="")
        serialized = serialize_post(parsed)
        assert serialized.startswith("---\n")
        # Second delimiter
        rest = serialized[4:]
        assert "\n---\n" in rest

    @PROPERTY_SETTINGS
    @given(raw=_frontmatter_markdown())
    def test_labels_are_hash_prefixed_in_serialized_output(self, raw: str) -> None:
        """Labels in serialized YAML use # prefix."""
        parsed = parse_post(raw, default_tz="UTC", default_author="")
        if not parsed.labels:
            return
        serialized = serialize_post(parsed)
        for label in parsed.labels:
            assert f"#{label}" in serialized
