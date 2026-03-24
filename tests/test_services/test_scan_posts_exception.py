"""Test that scan_posts narrows exception handling."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from backend.filesystem.content_manager import ContentManager

if TYPE_CHECKING:
    from pathlib import Path


class TestScanPostsNarrowException:
    def test_programming_error_propagates(self, tmp_path: Path):
        """A programming error (AttributeError) should NOT be silently caught."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        test_post = posts_dir / "test"
        test_post.mkdir()
        (test_post / "index.md").write_text("---\ntitle: test\n---\n# Hello")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)

        # Simulate a programming error in parse_post
        patch_target = "backend.filesystem.content_manager.parse_post"
        with patch(patch_target, side_effect=AttributeError("bug")):
            # This should NOT be silently caught
            import pytest

            with pytest.raises(AttributeError, match="bug"):
                cm.scan_posts()

    def test_yaml_error_is_caught_and_skipped(self, tmp_path: Path):
        """A YAML parse error should be caught and the post skipped."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        bad_post = posts_dir / "bad"
        bad_post.mkdir()
        (bad_post / "index.md").write_text("---\n: invalid yaml [\n---\n# Hello")
        good_post = posts_dir / "good"
        good_post.mkdir()
        (good_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Good Post")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)
        posts = cm.scan_posts()
        # Good post should be present, bad post should be skipped
        assert len(posts) == 1
        assert posts[0].title == "Good Post"

    def test_unicode_error_is_caught_and_skipped(self, tmp_path: Path):
        """A UnicodeDecodeError should be caught and the post skipped."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        binary_post = posts_dir / "binary"
        binary_post.mkdir()
        (binary_post / "index.md").write_bytes(b"\xff\xfe invalid utf8")
        good_post = posts_dir / "good"
        good_post.mkdir()
        (good_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Good")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)
        posts = cm.scan_posts()
        assert len(posts) == 1
