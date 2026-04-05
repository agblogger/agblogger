"""Tests for sync front matter normalization edge cases (Issue 12, 29)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import frontmatter as fm

from backend.services.sync_service import FileEntry, normalize_post_frontmatter
from backend.utils.datetime import format_datetime, now_utc

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

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["posts/new/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

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

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["posts/dt/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

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

        warnings, _modified = normalize_post_frontmatter(
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

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["labels.toml"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

    def test_path_traversal_skipped(self, tmp_path: Path) -> None:
        """Paths with traversal attempts are skipped."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)

        warnings, _modified = normalize_post_frontmatter(
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

        warnings, _modified = normalize_post_frontmatter(
            uploaded_files=["posts/date-only/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []

        post = fm.loads((content_dir / "posts/date-only/index.md").read_text())
        # Should be a normalized string
        assert isinstance(post["created_at"], str)
        assert "2026-02-02" in post["created_at"]


class TestNormalizationReturnsModifiedFiles:
    """Tests that normalization reports which files were actually modified on disk."""

    def _write_post(self, content_dir: Path, file_path: str, content: str) -> None:
        full_path = content_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def test_new_post_reported_as_modified(self, tmp_path: Path) -> None:
        """A new post that gets timestamps added should be in modified_files."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        self._write_post(content_dir, "posts/new/index.md", "# New Post\n\nContent.\n")

        warnings, modified_files = normalize_post_frontmatter(
            uploaded_files=["posts/new/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert warnings == []
        assert "posts/new/index.md" in modified_files

    def test_edited_post_reported_as_modified(self, tmp_path: Path) -> None:
        """An edited post (modified_at always updated) should be in modified_files."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        ts = "2026-01-15 10:30:00.000000+0000"
        post = fm.Post("Content.\n", title="Old", created_at=ts, modified_at=ts)
        self._write_post(content_dir, "posts/old/index.md", fm.dumps(post) + "\n")

        old_manifest = {
            "posts/old/index.md": FileEntry(
                file_path="posts/old/index.md",
                content_hash="abc",
                file_size=100,
                file_mtime="123",
            )
        }
        _warnings, modified_files = normalize_post_frontmatter(
            uploaded_files=["posts/old/index.md"],
            old_manifest=old_manifest,
            content_dir=content_dir,
        )
        assert "posts/old/index.md" in modified_files

    def test_unchanged_file_not_reported_as_modified(self, tmp_path: Path) -> None:
        """A post with fully-correct frontmatter that round-trips identically
        should NOT be reported as modified."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)

        # Build a file that is already perfectly normalized using fm.dumps
        ts = format_datetime(now_utc())
        post = fm.Post("Content here.\n", title="Perfect", created_at=ts, modified_at=ts)
        content = fm.dumps(post) + "\n"
        self._write_post(content_dir, "posts/perfect/index.md", content)

        # Not in old_manifest → is_edit=False → won't overwrite modified_at
        _warnings, modified_files = normalize_post_frontmatter(
            uploaded_files=["posts/perfect/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert "posts/perfect/index.md" not in modified_files

    def test_non_post_files_not_in_modified(self, tmp_path: Path) -> None:
        """Non-post files should never appear in modified_files."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "labels.toml").write_text("[labels]\n")

        _warnings, modified_files = normalize_post_frontmatter(
            uploaded_files=["labels.toml"],
            old_manifest={},
            content_dir=content_dir,
        )
        assert modified_files == []


class TestModifiedAtAfterMerge:
    """Regression: modified_at must not be set to created_at for merged posts
    missing modified_at (merge_frontmatter excludes it)."""

    def _write_post(self, content_dir: Path, file_path: str, content: str) -> None:
        full_path = content_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def test_merged_file_uses_current_time_not_created_at(self, tmp_path: Path) -> None:
        """When a merged file has modified_at excluded by merge and the manifest
        is empty (first sync), force_edit_paths should cause modified_at to be
        set to current time, not created_at."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        # Post with an old created_at but no modified_at (simulates merge output)
        self._write_post(
            content_dir,
            "posts/merged/index.md",
            "---\ntitle: Merged Post\ncreated_at: '2025-01-01 00:00:00.000000+0000'\n---\nBody.\n",
        )

        normalize_post_frontmatter(
            uploaded_files=["posts/merged/index.md"],
            old_manifest={},
            content_dir=content_dir,
            force_edit_paths={"posts/merged/index.md"},
        )

        post = fm.loads((content_dir / "posts/merged/index.md").read_text())
        # modified_at must NOT be the old created_at date
        assert "2025-01-01" not in post["modified_at"]

    def test_new_post_modified_at_equals_created_at(self, tmp_path: Path) -> None:
        """A truly new post (not merged) should have modified_at == created_at."""
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True)
        self._write_post(content_dir, "posts/fresh/index.md", "---\ntitle: Fresh\n---\nBody.\n")

        normalize_post_frontmatter(
            uploaded_files=["posts/fresh/index.md"],
            old_manifest={},
            content_dir=content_dir,
        )

        post = fm.loads((content_dir / "posts/fresh/index.md").read_text())
        assert post["modified_at"] == post["created_at"]
