"""Tests for YAML front matter parsing."""

from __future__ import annotations

import datetime

import frontmatter

from backend.filesystem.frontmatter import (
    RECOGNIZED_FIELDS,
    PostData,
    parse_post,
    serialize_post,
    strip_leading_heading,
)
from backend.services.datetime_service import now_utc


class TestRecognizedFields:
    def test_recognized_fields_contains_expected(self) -> None:
        assert "created_at" in RECOGNIZED_FIELDS
        assert "modified_at" in RECOGNIZED_FIELDS
        assert "author" in RECOGNIZED_FIELDS
        assert "labels" in RECOGNIZED_FIELDS
        assert "draft" in RECOGNIZED_FIELDS

    def test_author_username_not_in_recognized_fields(self) -> None:
        assert "author_username" not in RECOGNIZED_FIELDS

    def test_title_in_recognized_fields(self) -> None:
        assert "title" in RECOGNIZED_FIELDS

    def test_recognized_fields_is_frozenset(self) -> None:
        assert isinstance(RECOGNIZED_FIELDS, frozenset)


class TestFrontmatterParsing:
    def test_parse_basic_post(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
labels: ["#swe", "#ai"]
---
# Title

Blog post content
"""
        post = frontmatter.loads(content)
        # YAML auto-parses timestamps into datetime objects
        assert isinstance(post["created_at"], datetime.datetime)
        assert post["created_at"].year == 2026
        assert post["created_at"].month == 2
        assert post["created_at"].microsecond == 975359
        assert post["labels"] == ["#swe", "#ai"]
        assert post.content.startswith("# Title")

    def test_parse_minimal_post(self) -> None:
        content = """\
---
created_at: 2026-02-02
---
# Hello

Content here.
"""
        post = frontmatter.loads(content)
        # YAML auto-parses date-only values into date objects
        assert isinstance(post["created_at"], datetime.date)
        assert post["created_at"] == datetime.date(2026, 2, 2)
        assert "Hello" in post.content

    def test_parse_post_without_frontmatter(self) -> None:
        content = "# Just a title\n\nSome content.\n"
        post = frontmatter.loads(content)
        assert post.metadata == {}
        assert "Just a title" in post.content

    def test_title_extraction_from_heading(self) -> None:
        content = """\
---
created_at: 2026-01-01
---
# My Blog Post Title

Content follows the title.
"""
        post = frontmatter.loads(content)
        # Extract title from first # heading
        lines = post.content.strip().split("\n")
        title_line = next(
            (line for line in lines if line.startswith("# ")),
            None,
        )
        assert title_line is not None
        title = title_line.removeprefix("# ").strip()
        assert title == "My Blog Post Title"

    def test_roundtrip_frontmatter(self) -> None:
        post = frontmatter.Post(
            "# Title\n\nContent",
            created_at="2026-02-02 22:21:29.975359+00",
            labels=["#swe"],
        )
        dumped = frontmatter.dumps(post)
        reparsed = frontmatter.loads(dumped)
        assert reparsed["created_at"] == "2026-02-02 22:21:29.975359+00"
        assert reparsed["labels"] == ["#swe"]
        assert "# Title" in reparsed.content


class TestTitleFromFrontMatter:
    def test_title_from_frontmatter_field(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
title: My Front Matter Title
---

Body content without a heading.
"""
        post = parse_post(content, file_path="posts/test.md")
        assert post.title == "My Front Matter Title"

    def test_title_fallback_to_heading_when_not_in_frontmatter(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
---
# Heading Title

Body content.
"""
        post = parse_post(content, file_path="posts/test.md")
        assert post.title == "Heading Title"
        assert "# Heading Title" not in post.content

    def test_whitespace_title_falls_back_to_heading(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
title: "   "
---
# Heading Title

Body.
"""
        post = parse_post(content, file_path="posts/test.md")
        assert post.title == "Heading Title"
        assert "# Heading Title" not in post.content

    def test_numeric_title_coerced_to_string(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
title: 42
---

Body.
"""
        post = parse_post(content, file_path="posts/test.md")
        assert post.title == "42"

    def test_title_from_frontmatter_takes_precedence_over_heading(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
title: Front Matter Title
---
# Heading Title

Body content.
"""
        post = parse_post(content, file_path="posts/test.md")
        assert post.title == "Front Matter Title"
        # Heading is not stripped because it doesn't match the front matter title
        assert "# Heading Title" in post.content


class TestSerializePost:
    def test_labels_serialized_with_hash_prefix(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            content="# Test\n\nBody",
            raw_content="",
            created_at=now,
            modified_at=now,
            labels=["swe", "ai"],
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert parsed["labels"] == ["#swe", "#ai"]

    def test_draft_flag_present_when_true(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Draft",
            content="# Draft\n\nContent",
            raw_content="",
            created_at=now,
            modified_at=now,
            is_draft=True,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert parsed["draft"] is True

    def test_draft_flag_absent_when_false(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Published",
            content="# Published\n\nContent",
            raw_content="",
            created_at=now,
            modified_at=now,
            is_draft=False,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert "draft" not in parsed.metadata

    def test_author_included_when_present(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            content="# Test\n\nBody",
            raw_content="",
            created_at=now,
            modified_at=now,
            author="Alice",
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert parsed["author"] == "Alice"

    def test_author_omitted_when_none(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            content="# Test\n\nBody",
            raw_content="",
            created_at=now,
            modified_at=now,
            author=None,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert "author" not in parsed.metadata

    def test_timestamps_roundtrip(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            content="# Test\n\nBody",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        reparsed = parse_post(result)
        assert reparsed.created_at.year == now.year
        assert reparsed.created_at.month == now.month
        assert reparsed.created_at.day == now.day

    def test_full_roundtrip_through_parse(self) -> None:
        now = now_utc()
        original = PostData(
            title="Round Trip",
            content="# Round Trip\n\nFull content here.",
            raw_content="",
            created_at=now,
            modified_at=now,
            author="Admin",
            labels=["swe", "ai"],
            is_draft=True,
            file_path="posts/roundtrip.md",
        )
        serialized = serialize_post(original)
        reparsed = parse_post(serialized, file_path="posts/roundtrip.md")
        assert reparsed.title == "Round Trip"
        assert reparsed.labels == ["swe", "ai"]
        assert reparsed.is_draft is True
        assert reparsed.author == "Admin"
        assert "Full content here." in reparsed.content

    def test_title_written_to_frontmatter(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="My Title",
            content="Body content here.",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert parsed["title"] == "My Title"

    def test_leading_heading_stripped_from_body(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="My Title",
            content="# My Title\n\nBody content here.",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert not parsed.content.lstrip().startswith("# ")
        assert "Body content here." in parsed.content

    def test_heading_not_stripped_when_different_from_title(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="My Title",
            content="# Different Heading\n\nBody content.",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert "# Different Heading" in parsed.content


class TestAuthorParsing:
    def test_author_from_frontmatter(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
author: admin
---

Body content.
"""
        post = parse_post(content)
        assert post.author == "admin"

    def test_author_none_when_absent(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.author is None

    def test_author_none_when_empty_string(self) -> None:
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
author: ""
---

Body content.
"""
        post = parse_post(content)
        assert post.author is None

    def test_no_author_username_attribute(self) -> None:
        post = parse_post("---\ncreated_at: 2026-01-01\n---\nBody\n")
        assert not hasattr(post, "author_username")

    def test_no_default_author_parameter(self) -> None:
        """parse_post should not accept a default_author parameter."""
        import inspect

        sig = inspect.signature(parse_post)
        assert "default_author" not in sig.parameters

    def test_author_username_in_frontmatter_ignored(self) -> None:
        """author_username in front matter is not parsed into PostData."""
        content = """\
---
created_at: 2026-02-02 22:21:29.975359+00
author: admin
author_username: admin_user
---

Body content.
"""
        post = parse_post(content)
        assert post.author == "admin"
        assert not hasattr(post, "author_username")

    def test_author_whitespace_stripped(self) -> None:
        content = "---\ncreated_at: 2026-01-01\nauthor: '  Alice  '\n---\nBody\n"
        post = parse_post(content)
        assert post.author == "Alice"

    def test_serialize_does_not_write_author_username(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            content="Body",
            raw_content="",
            created_at=now,
            modified_at=now,
            author="admin",
        )
        result = serialize_post(post_data)
        assert "author_username" not in result


class TestStripLeadingHeading:
    def test_strips_matching_heading(self) -> None:
        assert strip_leading_heading("# Hello\n\nContent", "Hello") == "\nContent"

    def test_no_strip_when_no_heading(self) -> None:
        assert strip_leading_heading("Just content", "Title") == "Just content"

    def test_no_strip_when_heading_differs(self) -> None:
        content = "# Other\n\nContent"
        assert strip_leading_heading(content, "Title") == content

    def test_strips_with_leading_whitespace(self) -> None:
        assert strip_leading_heading("\n# Hello\n\nContent", "Hello") == "\nContent"

    def test_no_strip_for_h2_heading(self) -> None:
        content = "## Hello\n\nContent"
        assert strip_leading_heading(content, "Hello") == content
