"""Tests for normalize_post_frontmatter()."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import frontmatter as fm

from backend.services.sync_service import FileEntry, normalize_post_frontmatter


def _entry(path: str, hash_: str = "abc") -> FileEntry:
    return FileEntry(file_path=path, content_hash=hash_, file_size=100, file_mtime="1.0")


def _write_post(content_dir: Path, rel_path: str, content: str) -> None:
    full = content_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _read_post(content_dir: Path, rel_path: str) -> fm.Post:
    return fm.loads((content_dir / rel_path).read_text())


FROZEN_NOW = "2026-02-18 12:00:00.000000+0000"


class TestNormalizeNewPost:
    """Tests for new files (not in old_manifest)."""

    def test_fills_missing_created_at(self, tmp_path: Path) -> None:
        """File with no front matter gets created_at and modified_at filled."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            warnings, _modified = normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["created_at"] == FROZEN_NOW
        assert post["modified_at"] == FROZEN_NOW
        assert warnings == []

    def test_fills_missing_fields_preserves_existing(self, tmp_path: Path) -> None:
        """File with author: Alice keeps Alice, gets timestamps filled."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\nauthor: Alice\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["author"] == "Alice"
        assert post["created_at"] == FROZEN_NOW
        assert post["modified_at"] == FROZEN_NOW

    def test_new_post_created_at_equals_modified_at(self, tmp_path: Path) -> None:
        """Both timestamps are the same for new posts."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["created_at"] == post["modified_at"]

    def test_default_labels_empty_not_added(self, tmp_path: Path) -> None:
        """Labels field not added if not present (matches serialize_post convention)."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert "labels" not in post.metadata

    def test_default_draft_false_not_added(self, tmp_path: Path) -> None:
        """Draft field not added if not present (matches convention)."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert "draft" not in post.metadata

    def test_no_author_backfill_for_new_posts(self, tmp_path: Path) -> None:
        """A synced post with no author field remains without an author field."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert "author" not in post.metadata

    def test_invalid_created_at_is_replaced_with_current_time(self, tmp_path: Path) -> None:
        """Malformed created_at should not crash normalization for new posts."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\ncreated_at: ':'\n---\n# Hello\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            warnings, _modified = normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["created_at"] == FROZEN_NOW
        assert any("invalid created_at value" in warning for warning in warnings)


class TestNormalizeEditedPost:
    """Tests for edited files (in old_manifest)."""

    def test_edit_sets_modified_at_to_now(self, tmp_path: Path) -> None:
        """modified_at is updated to current time, created_at preserved."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ncreated_at: 2026-01-01 10:00:00.000000+00:00\n"
            "modified_at: 2026-01-01 10:00:00.000000+00:00\n"
            "author: admin\n---\n# Hello\n",
        )

        old_manifest = {"posts/hello/index.md": _entry("posts/hello/index.md")}

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["modified_at"] == FROZEN_NOW
        assert post["created_at"] == "2026-01-01 10:00:00.000000+0000"

    def test_edit_preserves_existing_author(self, tmp_path: Path) -> None:
        """Author from file is preserved during normalization."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\nauthor: Alice\ncreated_at: 2026-01-01 10:00:00.000000+00:00\n---\n# Hello\n",
        )

        old_manifest = {"posts/hello/index.md": _entry("posts/hello/index.md")}

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["author"] == "Alice"

    def test_edit_fills_missing_created_at(self, tmp_path: Path) -> None:
        """If created_at missing even on edit, fill it."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\nauthor: admin\n---\n# Hello\n",
        )

        old_manifest = {"posts/hello/index.md": _entry("posts/hello/index.md")}

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["created_at"] == FROZEN_NOW

    def test_edit_invalid_created_at_is_replaced(self, tmp_path: Path) -> None:
        """Malformed created_at should not crash normalization for edited posts."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ncreated_at: 0\nauthor: admin\n---\n# Hello\n",
        )

        old_manifest = {"posts/hello/index.md": _entry("posts/hello/index.md")}

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            warnings, _modified = normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["created_at"] == FROZEN_NOW
        assert post["modified_at"] == FROZEN_NOW
        assert any("invalid created_at value" in warning for warning in warnings)


class TestNormalizeUnrecognizedFields:
    """Tests for unrecognized field warnings."""

    def test_unrecognized_field_warns(self, tmp_path: Path) -> None:
        """File with custom_field and tags produces 2 warnings."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ncustom_field: hello\ntags:\n  - a\n  - b\n---\n# Hello\n",
        )

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            warnings, _modified = normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        assert len(warnings) == 2
        assert any("custom_field" in w for w in warnings)
        assert any("tags" in w for w in warnings)

    def test_unrecognized_field_preserved_in_file(self, tmp_path: Path) -> None:
        """Unrecognized fields remain in the file after normalization."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ncustom_field: hello\n---\n# Hello\n",
        )

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["custom_field"] == "hello"


class TestNormalizeTitleBackfill:
    """Tests for title backfill during sync normalization."""

    def test_title_backfilled_from_heading(self, tmp_path: Path) -> None:
        """Post without title in front matter gets it from first heading."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/hello/index.md", "---\n---\n# My Post Title\n\nContent.\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["title"] == "My Post Title"
        assert not post.content.lstrip().startswith("# ")

    def test_title_preserved_when_already_present(self, tmp_path: Path) -> None:
        """Post with title in front matter keeps it unchanged."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ntitle: Explicit Title\n---\n\nContent.\n",
        )

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["title"] == "Explicit Title"

    def test_title_from_filename_when_no_heading(self, tmp_path: Path) -> None:
        """Post without title or heading gets title derived from filename."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(content_dir, "posts/my-cool-post/index.md", "---\n---\nJust content.\n")

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/my-cool-post/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/my-cool-post/index.md")
        assert post["title"] == "My Cool Post"

    def test_title_backfill_on_edited_post(self, tmp_path: Path) -> None:
        """Edited post without title gets it backfilled from heading."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ncreated_at: 2026-01-01 10:00:00.000000+00:00\n"
            "author: admin\n---\n# Edited Title\n\nContent.\n",
        )
        old_manifest = {"posts/hello/index.md": _entry("posts/hello/index.md")}

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["title"] == "Edited Title"
        assert not post.content.lstrip().startswith("# ")

    def test_empty_title_in_frontmatter_gets_backfilled(self, tmp_path: Path) -> None:
        """Post with empty title string in front matter gets it from heading."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        _write_post(
            content_dir,
            "posts/hello/index.md",
            "---\ntitle: ''\n---\n# Real Title\n\nContent.\n",
        )

        with patch("backend.services.sync_service.now_utc") as mock_now:
            from datetime import UTC, datetime

            mock_now.return_value = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
            normalize_post_frontmatter(
                uploaded_files=["posts/hello/index.md"],
                old_manifest={},
                content_dir=content_dir,
            )

        post = _read_post(content_dir, "posts/hello/index.md")
        assert post["title"] == "Real Title"
        assert not post.content.lstrip().startswith("# ")


class TestNormalizeSkipNonPosts:
    """Tests for files that should be skipped."""

    def test_skips_non_md_files(self, tmp_path: Path) -> None:
        """index.toml is not modified."""
        content_dir = tmp_path / "content"
        content_dir.mkdir(parents=True)
        original = '[site]\ntitle = "Test"\n'
        (content_dir / "index.toml").write_text(original)

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["index.toml"],
            old_manifest={},
            content_dir=content_dir,
        )

        assert warnings == []
        assert (content_dir / "index.toml").read_text() == original

    def test_skips_md_outside_posts(self, tmp_path: Path) -> None:
        """about.md is not modified."""
        content_dir = tmp_path / "content"
        content_dir.mkdir(parents=True)
        original = "---\ntitle: About\n---\n# About\n"
        (content_dir / "about.md").write_text(original)

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["about.md"],
            old_manifest={},
            content_dir=content_dir,
        )

        assert warnings == []
        assert (content_dir / "about.md").read_text() == original

    def test_skips_nonexistent_file(self, tmp_path: Path) -> None:
        """Missing file doesn't crash."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["posts/missing/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )

        assert warnings == []
