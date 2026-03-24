"""Tests for sync front matter normalization edge cases (Issue 12, 29)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.services.sync_service import FileEntry, normalize_post_frontmatter

if TYPE_CHECKING:
    from pathlib import Path


class TestFrontMatterNormalization:
    def _write_post(self, content_dir: Path, file_path: str, content: str) -> None:
        full_path = content_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def test_new_post_gets_timestamps(self, tmp_path: Path) -> None:
        """New posts get created_at and modified_at filled in."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        self._write_post(content_dir, "posts/new/index.md", "# New Post\n\nContent.\n")

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/new/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

        import frontmatter as fm

        post = fm.loads((content_dir / "posts/new/index.md").read_text())
        assert "created_at" in post.metadata
        assert "modified_at" in post.metadata

    def test_edited_post_updates_modified_at(self, tmp_path: Path) -> None:
        """Edited posts have modified_at updated."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        self._write_post(
            content_dir,
            "posts/existing/index.md",
            "---\ncreated_at: '2026-01-01T00:00:00+00:00'\nauthor: admin\n---\n# Existing\n",
        )
        old_manifest = {
            "posts/existing/index.md": FileEntry(
                file_path="posts/existing/index.md",
                content_hash="abc123",
                file_size=100,
                file_mtime="12345",
            )
        }

        normalize_post_frontmatter(
            uploaded_files=["posts/existing/index.md"],
            old_manifest=old_manifest,
            content_dir=content_dir,
        )

        import frontmatter as fm

        post = fm.loads((content_dir / "posts/existing/index.md").read_text())
        assert "2026-01-01" in post["created_at"]
        assert post["modified_at"] != post["created_at"]

    def test_datetime_object_in_frontmatter(self, tmp_path: Path) -> None:
        """Issue 12: YAML parser may return datetime objects directly."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        # YAML with unquoted datetime — python-frontmatter may parse as datetime
        self._write_post(
            content_dir,
            "posts/dt/index.md",
            "---\ncreated_at: 2026-02-02 22:21:29+00:00\n---\n# Post\n",
        )

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/dt/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

        import frontmatter as fm

        post = fm.loads((content_dir / "posts/dt/index.md").read_text())
        # Should be a string now, not a datetime object
        assert isinstance(post["created_at"], str)

    def test_unrecognized_fields_warn(self, tmp_path: Path) -> None:
        """Unrecognized front matter fields produce warnings."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        self._write_post(
            content_dir,
            "posts/custom/index.md",
            "---\ncustom_field: hello\nweird_key: 42\n---\n# Custom\n",
        )

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/custom/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert any("custom_field" in w for w in warnings)
        assert any("weird_key" in w for w in warnings)

    def test_non_post_files_skipped(self, tmp_path: Path) -> None:
        """Non-post files (not under posts/ or not .md) are not normalized."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "labels.toml").write_text("[labels]\n")

        warnings = normalize_post_frontmatter(
            uploaded_files=["labels.toml"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

    def test_path_traversal_skipped(self, tmp_path: Path) -> None:
        """Paths with traversal attempts are skipped."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/../../etc/passwd"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

    def test_date_object_in_frontmatter(self, tmp_path: Path) -> None:
        """Issue 29: YAML parser may return date objects (not datetime)."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        # YAML with just a date (no time component)
        self._write_post(
            content_dir,
            "posts/date-only/index.md",
            "---\ncreated_at: 2026-02-02\n---\n# Date Only\n",
        )

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/date-only/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

        import frontmatter as fm

        post = fm.loads((content_dir / "posts/date-only/index.md").read_text())
        # Should be a normalized string
        assert isinstance(post["created_at"], str)
        assert "2026-02-02" in post["created_at"]
