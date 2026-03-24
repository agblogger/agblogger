"""Tests for content manager and filesystem operations."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.filesystem.content_manager import (
    ContentManager,
    discover_posts,
    hash_content,
)
from backend.filesystem.frontmatter import (
    PostData,
    extract_title,
    generate_markdown_excerpt,
    parse_labels,
    parse_post,
)
from backend.filesystem.toml_manager import parse_labels_config, parse_site_config

if TYPE_CHECKING:
    from pathlib import Path


class TestHashContent:
    def test_hash_string(self) -> None:
        h = hash_content("hello")
        assert len(h) == 64  # SHA-256 hex digest
        assert h == hash_content("hello")

    def test_hash_different_content(self) -> None:
        assert hash_content("a") != hash_content("b")


class TestExtractTitle:
    def test_heading(self) -> None:
        assert extract_title("# My Title\n\nContent") == "My Title"

    def test_no_heading_fallback_to_filename(self) -> None:
        assert extract_title("No heading here", "hello-world.md") == "Hello World"

    def test_date_prefix_stripped(self) -> None:
        title = extract_title("No heading", "2026-02-02-my-post.md")
        assert title == "My Post"

    def test_directory_backed_post_uses_parent_directory_name(self) -> None:
        title = extract_title("No heading", "posts/2026-02-02-my-post/index.md")
        assert title == "My Post"

    def test_untitled(self) -> None:
        assert extract_title("No heading here") == "Untitled"


class TestParseLabels:
    def test_hash_labels(self) -> None:
        assert parse_labels(["#swe", "#ai"]) == ["swe", "ai"]

    def test_plain_labels(self) -> None:
        assert parse_labels(["cooking"]) == ["cooking"]

    def test_empty(self) -> None:
        assert parse_labels(None) == []
        assert parse_labels([]) == []


class TestGenerateMarkdownExcerpt:
    def test_preserves_bold(self) -> None:
        content = "This is **bold** text."
        excerpt = generate_markdown_excerpt(content)
        assert "**bold**" in excerpt

    def test_preserves_links(self) -> None:
        content = "Check [this link](https://example.com) out."
        excerpt = generate_markdown_excerpt(content)
        assert "[this link](https://example.com)" in excerpt

    def test_preserves_inline_math(self) -> None:
        content = "The formula $E = mc^2$ is famous."
        excerpt = generate_markdown_excerpt(content)
        assert "$E = mc^2$" in excerpt

    def test_strips_headings(self) -> None:
        content = "# Title\n\nBody text here."
        excerpt = generate_markdown_excerpt(content)
        assert "Title" not in excerpt
        assert "Body text here." in excerpt

    def test_strips_code_blocks(self) -> None:
        content = "Before.\n\n```python\nprint('hi')\n```\n\nAfter."
        excerpt = generate_markdown_excerpt(content)
        assert "print" not in excerpt
        assert "Before." in excerpt
        assert "After." in excerpt

    def test_truncation(self) -> None:
        content = "Word " * 100
        excerpt = generate_markdown_excerpt(content, max_length=50)
        assert len(excerpt) <= 53  # 50 + "..."
        assert excerpt.endswith("...")

    def test_strips_display_math(self) -> None:
        content = "Before.\n\n$$\n\\int_0^1 x dx\n$$\n\nAfter."
        excerpt = generate_markdown_excerpt(content)
        assert "\\int" not in excerpt
        assert "$$" not in excerpt
        assert "Before." in excerpt
        assert "After." in excerpt

    def test_strips_table_lines(self) -> None:
        content = "Before.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter."
        excerpt = generate_markdown_excerpt(content)
        assert "|" not in excerpt
        assert "Before." in excerpt
        assert "After." in excerpt

    def test_preserves_inline_math_with_display_math_stripped(self) -> None:
        content = "Inline $x^2$ here.\n\n$$\ny = mx + b\n$$\n\nMore text."
        excerpt = generate_markdown_excerpt(content)
        assert "$x^2$" in excerpt
        assert "y = mx" not in excerpt
        assert "More text." in excerpt


class TestParsePost:
    def test_basic_post(self) -> None:
        content = """---
created_at: 2026-02-02 22:21:29.975359+00
labels: ["#swe", "#ai"]
---
# My Post

Content here.
"""
        post = parse_post(content, file_path="posts/test/index.md")
        assert post.title == "My Post"
        assert post.created_at.year == 2026
        assert "swe" in post.labels
        assert "ai" in post.labels
        assert not post.is_draft

    def test_draft_post(self) -> None:
        content = """---
created_at: 2026-01-01
draft: true
---
# Draft

Not published yet.
"""
        post = parse_post(content)
        assert post.is_draft is True

    def test_no_frontmatter(self) -> None:
        content = "# Just a title\n\nSome content."
        post = parse_post(content, file_path="posts/simple/index.md")
        assert post.title == "Just a title"
        assert post.labels == []


class TestSiteConfig:
    def test_parse_config(self, tmp_content_dir: Path) -> None:
        config = parse_site_config(tmp_content_dir)
        assert config.title == "Test Blog"
        assert config.timezone == "UTC"
        assert len(config.pages) >= 1

    def test_missing_config(self, tmp_path: Path) -> None:
        config = parse_site_config(tmp_path)
        assert config.title == "My Blog"


class TestLabelsConfig:
    def test_parse_empty(self, tmp_content_dir: Path) -> None:
        labels = parse_labels_config(tmp_content_dir)
        assert labels == {}

    def test_parse_with_entries(self, tmp_path: Path) -> None:
        labels_path = tmp_path / "labels.toml"
        labels_path.write_text(
            '[labels]\n[labels.swe]\nnames = ["software engineering"]\nparent = "#cs"\n'
            "[labels.cs]\nnames = []\n"
        )
        labels = parse_labels_config(tmp_path)
        assert "swe" in labels
        assert labels["swe"].parents == ["cs"]


class TestContentManager:
    def test_scan_empty(self, tmp_content_dir: Path) -> None:
        cm = ContentManager(content_dir=tmp_content_dir)
        posts = cm.scan_posts()
        assert posts == []

    def test_scan_with_posts(self, tmp_content_dir: Path) -> None:
        post_dir = tmp_content_dir / "posts" / "test"
        post_dir.mkdir(parents=True)
        (post_dir / "index.md").write_text("---\ncreated_at: 2026-01-01\n---\n# Test\n\nContent.\n")
        cm = ContentManager(content_dir=tmp_content_dir)
        posts = cm.scan_posts()
        assert len(posts) == 1
        assert posts[0].title == "Test"

    def test_discover_posts(self, tmp_content_dir: Path) -> None:
        posts_dir = tmp_content_dir / "posts"
        a_dir = posts_dir / "a"
        a_dir.mkdir(parents=True)
        (a_dir / "index.md").write_text("# A")
        sub = posts_dir / "sub" / "b"
        sub.mkdir(parents=True)
        (sub / "index.md").write_text("# B")
        found = discover_posts(tmp_content_dir)
        assert len(found) == 2

    def test_write_and_read_post(self, tmp_content_dir: Path) -> None:
        cm = ContentManager(content_dir=tmp_content_dir)
        post = parse_post(
            "---\ncreated_at: 2026-01-01\n---\n# Written\n\nBody.\n",
            file_path="posts/written/index.md",
        )
        cm.write_post("posts/written/index.md", post)
        read_back = cm.read_post("posts/written/index.md")
        assert read_back is not None
        assert read_back.title == "Written"

    def test_subdirectory_post_has_no_implicit_labels(self, tmp_content_dir: Path) -> None:
        """Posts in subdirectories should only have their front matter labels."""
        sub = tmp_content_dir / "posts" / "cooking" / "recipe"
        sub.mkdir(parents=True)
        (sub / "index.md").write_text(
            "---\ncreated_at: 2026-01-01\nlabels: ['#swe']\n---\n# Recipe\n\nContent.\n"
        )
        cm = ContentManager(content_dir=tmp_content_dir)
        posts = cm.scan_posts()
        assert len(posts) == 1
        assert posts[0].labels == ["swe"]

    def test_delete_post(self, tmp_content_dir: Path) -> None:
        post_dir = tmp_content_dir / "posts" / "to-delete"
        post_dir.mkdir(parents=True)
        (post_dir / "index.md").write_text("# Delete me")
        cm = ContentManager(content_dir=tmp_content_dir)
        assert cm.delete_post("posts/to-delete/index.md") is True
        assert cm.delete_post("posts/nonexistent/index.md") is False


class TestPlainExcerptRegexSafety:
    """get_plain_excerpt must not exhibit quadratic regex behavior."""

    def test_adversarial_asterisks_completes_quickly(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "index.toml").write_text('[site]\ntitle = "T"\n')
        (content_dir / "labels.toml").write_text("[labels]\n")
        cm = ContentManager(content_dir)

        # Adversarial content: many unclosed * that cause backtracking
        adversarial = "* " * 5000
        now = datetime(2026, 1, 1, tzinfo=UTC)
        post_data = PostData(
            file_path="posts/test/index.md",
            title="Test",
            author="admin",
            created_at=now,
            modified_at=now,
            content=adversarial,
            raw_content=adversarial,
            labels=[],
        )

        start = time.monotonic()
        cm.get_plain_excerpt(post_data)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Regex took {elapsed:.1f}s — backtracking detected"


class TestDeletePostSymlink:
    """Deleting a symlinked post directory must not delete the symlink target."""

    def test_delete_symlinked_post_does_not_delete_target(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        posts_dir = content_dir / "posts"
        posts_dir.mkdir()
        (content_dir / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (content_dir / "labels.toml").write_text("[labels]\n")

        real_dir = posts_dir / "2026-01-01-real-post"
        real_dir.mkdir()
        (real_dir / "index.md").write_text("---\ntitle: Real\n---\nContent")
        (real_dir / "image.png").write_bytes(b"PNG")

        symlink_dir = posts_dir / "2026-01-01-old-name"
        symlink_dir.symlink_to(real_dir)

        cm = ContentManager(content_dir)
        cm.delete_post("posts/2026-01-01-old-name/index.md", delete_assets=True)

        assert real_dir.exists()
        assert (real_dir / "index.md").exists()
        assert (real_dir / "image.png").exists()
        assert not symlink_dir.exists()
