"""Tests for the sync service."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from backend.services.sync_service import (
    ChangeType,
    FileEntry,
    compute_sync_plan,
    is_sync_managed_path,
    scan_content_files,
)

if TYPE_CHECKING:
    import os


def _entry(path: str, hash_: str = "abc", size: int = 100) -> FileEntry:
    return FileEntry(file_path=path, content_hash=hash_, file_size=size, file_mtime="1.0")


class TestComputeSyncPlan:
    def test_no_changes(self) -> None:
        manifest = {"a.md": _entry("a.md", "aaa")}
        client = {"a.md": _entry("a.md", "aaa")}
        server = {"a.md": _entry("a.md", "aaa")}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.no_change
        assert plan.to_upload == []
        assert plan.to_download == []

    def test_local_modification(self) -> None:
        manifest = {"a.md": _entry("a.md", "old")}
        client = {"a.md": _entry("a.md", "new")}
        server = {"a.md": _entry("a.md", "old")}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.to_upload

    def test_remote_modification(self) -> None:
        manifest = {"a.md": _entry("a.md", "old")}
        client = {"a.md": _entry("a.md", "old")}
        server = {"a.md": _entry("a.md", "new")}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.to_download

    def test_conflict(self) -> None:
        manifest = {"a.md": _entry("a.md", "old")}
        client = {"a.md": _entry("a.md", "client_new")}
        server = {"a.md": _entry("a.md", "server_new")}
        plan = compute_sync_plan(client, manifest, server)
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].file_path == "a.md"
        assert plan.conflicts[0].change_type == ChangeType.CONFLICT

    def test_both_same_change(self) -> None:
        """Both modified to same content = no conflict."""
        manifest = {"a.md": _entry("a.md", "old")}
        client = {"a.md": _entry("a.md", "same_new")}
        server = {"a.md": _entry("a.md", "same_new")}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.no_change

    def test_local_addition(self) -> None:
        plan = compute_sync_plan(
            {"new.md": _entry("new.md", "abc")},
            {},
            {},
        )
        assert "new.md" in plan.to_upload

    def test_remote_addition(self) -> None:
        plan = compute_sync_plan(
            {},
            {},
            {"remote.md": _entry("remote.md", "xyz")},
        )
        assert "remote.md" in plan.to_download

    def test_local_deletion(self) -> None:
        manifest = {"a.md": _entry("a.md", "hash")}
        client: dict[str, FileEntry] = {}
        server = {"a.md": _entry("a.md", "hash")}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.to_delete_remote

    def test_local_delete_remote_modify_conflict(self) -> None:
        """Local delete + remote modify should not auto-delete remote content."""
        manifest = {"a.md": _entry("a.md", "old")}
        client: dict[str, FileEntry] = {}
        server = {"a.md": _entry("a.md", "new")}
        plan = compute_sync_plan(client, manifest, server)
        assert plan.to_delete_remote == []
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].file_path == "a.md"
        assert plan.conflicts[0].change_type == ChangeType.DELETE_MODIFY_CONFLICT

    def test_remote_deletion(self) -> None:
        manifest = {"a.md": _entry("a.md", "hash")}
        client = {"a.md": _entry("a.md", "hash")}
        server: dict[str, FileEntry] = {}
        plan = compute_sync_plan(client, manifest, server)
        assert "a.md" in plan.to_delete_local

    def test_both_deleted(self) -> None:
        manifest = {"a.md": _entry("a.md", "hash")}
        plan = compute_sync_plan({}, manifest, {})
        assert "a.md" in plan.no_change

    def test_independent_additions_same_content(self) -> None:
        """Both sides add same file with same content."""
        client = {"new.md": _entry("new.md", "same")}
        server = {"new.md": _entry("new.md", "same")}
        plan = compute_sync_plan(client, {}, server)
        assert "new.md" in plan.no_change

    def test_independent_additions_different_content(self) -> None:
        """Both sides add same file with different content = conflict."""
        client = {"new.md": _entry("new.md", "aaa")}
        server = {"new.md": _entry("new.md", "bbb")}
        plan = compute_sync_plan(client, {}, server)
        assert len(plan.conflicts) == 1

    def test_delete_modify_conflict(self) -> None:
        """Server deleted, client modified = conflict."""
        manifest = {"a.md": _entry("a.md", "original")}
        client = {"a.md": _entry("a.md", "modified")}
        server: dict[str, FileEntry] = {}
        plan = compute_sync_plan(client, manifest, server)
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].change_type == ChangeType.DELETE_MODIFY_CONFLICT

    def test_multiple_files_mixed(self) -> None:
        manifest = {
            "keep.md": _entry("keep.md", "same"),
            "push.md": _entry("push.md", "old"),
            "pull.md": _entry("pull.md", "old"),
        }
        client = {
            "keep.md": _entry("keep.md", "same"),
            "push.md": _entry("push.md", "new_local"),
            "pull.md": _entry("pull.md", "old"),
            "added.md": _entry("added.md", "fresh"),
        }
        server = {
            "keep.md": _entry("keep.md", "same"),
            "push.md": _entry("push.md", "old"),
            "pull.md": _entry("pull.md", "new_remote"),
        }
        plan = compute_sync_plan(client, manifest, server)
        assert "keep.md" in plan.no_change
        assert "push.md" in plan.to_upload
        assert "pull.md" in plan.to_download
        assert "added.md" in plan.to_upload


class TestIsSyncManagedPath:
    """Unit tests for the sync path security gate."""

    # ── Positive cases: allowed paths ──

    def test_allows_index_toml(self) -> None:
        assert is_sync_managed_path("index.toml") is True

    def test_allows_labels_toml(self) -> None:
        assert is_sync_managed_path("labels.toml") is True

    def test_allows_top_level_md(self) -> None:
        assert is_sync_managed_path("about.md") is True

    def test_allows_posts_files(self) -> None:
        assert is_sync_managed_path("posts/2026-02-02-hello/index.md") is True

    def test_allows_nested_post_assets(self) -> None:
        assert is_sync_managed_path("posts/2026-02-02-hello/assets/photo.png") is True
        assert is_sync_managed_path("posts/2026-02-02-hello/images/diagrams/arch.svg") is True

    def test_allows_shared_assets(self) -> None:
        assert is_sync_managed_path("assets/logo.png") is True
        assert is_sync_managed_path("assets/images/banner.jpg") is True

    # ── Negative cases: rejected paths ──

    def test_rejects_empty_path(self) -> None:
        assert is_sync_managed_path("") is False

    def test_rejects_whitespace_only(self) -> None:
        assert is_sync_managed_path("   ") is False

    def test_rejects_hidden_files_at_root(self) -> None:
        assert is_sync_managed_path(".env") is False
        assert is_sync_managed_path(".atproto-oauth-key.json") is False
        assert is_sync_managed_path(".agblogger-manifest.json") is False

    def test_rejects_hidden_files_in_subdirectory(self) -> None:
        assert is_sync_managed_path("posts/.hidden") is False
        assert is_sync_managed_path("posts/2026-02-02-hello/.secret") is False

    def test_rejects_hidden_directory_components(self) -> None:
        assert is_sync_managed_path("posts/.hidden/index.md") is False
        assert is_sync_managed_path(".secrets/key.json") is False

    def test_rejects_dotdot_traversal(self) -> None:
        assert is_sync_managed_path("../etc/passwd") is False
        assert is_sync_managed_path("posts/../../etc/passwd") is False
        assert is_sync_managed_path("posts/../../../secret") is False

    def test_rejects_dot_segments(self) -> None:
        assert is_sync_managed_path("./posts/index.md") is False
        assert is_sync_managed_path("posts/./index.md") is False

    def test_rejects_paths_outside_allowed_prefixes(self) -> None:
        assert is_sync_managed_path("config/something.toml") is False
        assert is_sync_managed_path("backups/db.sql") is False
        assert is_sync_managed_path("random.txt") is False

    def test_rejects_non_md_top_level_files(self) -> None:
        assert is_sync_managed_path("data.json") is False
        assert is_sync_managed_path("config.toml") is False


class TestScanContentFiles:
    def test_allows_nested_assets_inside_post_directories(self, tmp_path: Path) -> None:
        assert is_sync_managed_path("posts/2026-02-02-hello-world/assets/photo.png")
        assert is_sync_managed_path("posts/2026-02-02-hello-world/images/diagrams/arch.svg")

    def test_excludes_git_directory(self, tmp_path: Path) -> None:
        (tmp_path / "post.md").write_text("hello")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main")
        entries = scan_content_files(tmp_path)
        assert "post.md" in entries
        assert not any(".git" in p for p in entries)

    def test_excludes_dot_files(self, tmp_path: Path) -> None:
        (tmp_path / "post.md").write_text("hello")
        (tmp_path / ".env").write_text("SECRET=x")
        (tmp_path / ".agblogger-manifest.json").write_text("{}")
        entries = scan_content_files(tmp_path)
        assert "post.md" in entries
        assert ".env" not in entries
        assert ".agblogger-manifest.json" not in entries

    def test_excludes_dot_files_in_subdirectories(self, tmp_path: Path) -> None:
        sub = tmp_path / "posts"
        sub.mkdir()
        post_dir = sub / "post"
        post_dir.mkdir()
        (post_dir / "index.md").write_text("hello")
        (sub / ".hidden").write_text("secret")
        entries = scan_content_files(tmp_path)
        assert "posts/post/index.md" in entries
        assert "posts/.hidden" not in entries


class TestScanContentFilesPerFileError:
    """Scan skips files that fail with OSError and continues."""

    def test_stat_error_skips_file_and_returns_others(self, tmp_path: Path) -> None:
        (tmp_path / "good.md").write_text("hello")
        (tmp_path / "bad.md").write_text("world")

        original_stat = Path.stat

        def mock_stat(self: Path, **kwargs: object) -> os.stat_result:
            if self.name == "bad.md":
                raise PermissionError("denied")
            return original_stat(self)

        with patch("pathlib.Path.stat", mock_stat):
            entries = scan_content_files(tmp_path)

        assert "good.md" in entries
        assert "bad.md" not in entries
