"""Tests for CLI sync client."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cli.sync_client import SyncClient, validate_server_url


class TestValidateServerUrl:
    def test_rejects_insecure_http_for_remote_hosts(self) -> None:
        with pytest.raises(ValueError, match="HTTPS is required"):
            validate_server_url("http://example.com")

    def test_allows_https_for_remote_hosts(self) -> None:
        assert validate_server_url("https://example.com") == "https://example.com"

    def test_allows_http_for_localhost(self) -> None:
        assert validate_server_url("http://localhost:8000") == "http://localhost:8000"

    def test_allows_insecure_http_when_flag_enabled(self) -> None:
        assert (
            validate_server_url("http://example.com:8000", allow_insecure_http=True)
            == "http://example.com:8000"
        )


class TestSyncDeleteCounting:
    """Tests that the sync total only counts files that were actually deleted."""

    def test_total_excludes_nonexistent_files_from_delete_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When to_delete_local contains files that don't exist on disk,
        the total should only count files that were actually deleted."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Create one file that WILL be deleted
        existing_file = content_dir / "existing.md"
        existing_file.write_text("delete me")

        # "nonexistent.md" does NOT exist on disk

        # Mock status() to return a plan with 2 files to delete locally
        status_response = {
            "to_upload": [],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": ["existing.md", "nonexistent.md"],
            "conflicts": [],
        }

        # Mock the commit response
        commit_response = {
            "to_download": [],
            "conflicts": [],
            "warnings": [],
            "commit_hash": "abc123",
        }

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = commit_response

        with (
            patch.object(SyncClient, "status", return_value=status_response),
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_save_commit_hash"),
            patch("cli.sync_client.scan_local_files", return_value={}),
            patch("cli.sync_client.save_manifest"),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()
            client.client.post.return_value = mock_post

            client.sync()

        captured = capsys.readouterr()
        # Only 1 file was actually deleted (existing.md), nonexistent.md was skipped.
        # The total should be 1 (0 uploads + 0 downloads + 1 delete), not 2.
        assert "1 file(s) synced" in captured.out
        assert "0 conflict(s)" in captured.out


class TestSyncCountsUniqueFiles:
    """Regression: sync total should count unique files, not operations.

    When a conflict file is both uploaded and downloaded, it should be
    counted as 1 synced file, not 2.
    """

    def test_conflict_file_counted_once_not_twice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts" / "conflict-post").mkdir(parents=True)

        # File that will be uploaded as a conflict
        conflict_file = content_dir / "posts" / "conflict-post" / "index.md"
        conflict_file.write_text("---\ntitle: Local\n---\nlocal body\n")

        # Plan: the file is a conflict (both sides changed)
        status_response = {
            "to_upload": [],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": [],
            "conflicts": [
                {
                    "file_path": "posts/conflict-post/index.md",
                    "action": "merge",
                    "change_type": "conflict",
                }
            ],
        }

        # Server responds: merged file needs re-download
        commit_response = {
            "to_download": ["posts/conflict-post/index.md"],
            "conflicts": [],
            "warnings": [],
            "commit_hash": "abc123",
        }

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = commit_response

        with (
            patch.object(SyncClient, "status", return_value=status_response),
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_save_commit_hash"),
            patch.object(SyncClient, "_download_file", return_value=True),
            patch("cli.sync_client.scan_local_files", return_value={}),
            patch("cli.sync_client.save_manifest"),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()
            client.client.post.return_value = mock_post

            client.sync()

        captured = capsys.readouterr()
        # File was both uploaded and downloaded, but should count as 1 unique file
        assert "1 file(s) synced" in captured.out


class TestSyncClientLogin:
    def test_login_uses_session_login_endpoint_and_stores_csrf_token(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"csrf_token": "cli-csrf"}

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir
        client.server_url = "http://localhost:8000"
        client._csrf_token = None
        client.client = MagicMock()
        client.client.post.return_value = response

        client.login("admin", "admin123")

        assert client._csrf_token == "cli-csrf"
        client.client.post.assert_called_once_with(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )

    def test_close_revokes_session_refresh_token_before_closing(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        response = MagicMock()
        response.raise_for_status = MagicMock()

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir
        client.server_url = "http://localhost:8000"
        client._csrf_token = "cli-csrf"
        client.client = MagicMock()
        client.client.headers = {}
        client.client.post.return_value = response

        client.close()

        client.client.post.assert_called_once_with(
            "/api/auth/logout",
            headers={"X-CSRF-Token": "cli-csrf"},
            json={},
        )
        response.raise_for_status.assert_called_once_with()
        assert client.__dict__["_csrf_token"] is None
        client.client.close.assert_called_once_with()

    def test_close_warns_and_still_closes_on_logout_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        import httpx

        request = httpx.Request("POST", "http://localhost:8000/api/auth/logout")
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "logout failed",
            request=request,
            response=httpx.Response(status_code=500, request=request),
        )

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir
        client.server_url = "http://localhost:8000"
        client._csrf_token = "cli-csrf"
        client.client = MagicMock()
        client.client.headers = {}
        client.client.post.return_value = response

        client.close()

        captured = capsys.readouterr()
        assert "Warning: failed to revoke CLI session on exit" in captured.err
        assert client.__dict__["_csrf_token"] is None
        client.client.close.assert_called_once_with()


class TestSyncDeletePrunesEmptyDirectories:
    """Deleting a local file during sync should remove empty parent directories."""

    def test_delete_local_prunes_empty_parent_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        post_dir = content_dir / "posts" / "deleteme"
        post_dir.mkdir(parents=True)
        (post_dir / "index.md").write_text("Body")
        # Create another post so posts/ itself isn't empty after pruning
        other_post = content_dir / "posts" / "keep"
        other_post.mkdir()
        (other_post / "index.md").write_text("Keep me")

        plan = {
            "to_upload": [],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": ["posts/deleteme/index.md"],
            "conflicts": [],
        }
        commit_response = {
            "to_download": [],
            "conflicts": [],
            "warnings": [],
            "commit_hash": "abc123",
        }

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = commit_response

        with (
            patch.object(SyncClient, "status", return_value=plan),
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_save_commit_hash"),
            patch("cli.sync_client.scan_local_files", return_value={}),
            patch("cli.sync_client.save_manifest"),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()
            client.client.post.return_value = mock_post

            client.sync(plan)

        # File should be deleted
        assert not (post_dir / "index.md").exists()
        # Empty parent directory should be pruned
        assert not post_dir.exists()
        # But posts/ should still exist
        assert (content_dir / "posts").exists()


class TestSaveCommitHashResilience:
    """_save_commit_hash must not crash when the config file is corrupted."""

    def test_corrupted_config_does_not_crash(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Write corrupted config
        (content_dir / ".agblogger.json").write_text("NOT VALID JSON {{{")

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir

        # Should not crash (currently calls sys.exit(1) via load_config)
        client._save_commit_hash("abc123")

        # Should warn on stderr
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "warning" in captured.err.lower()

    def test_missing_config_saves_successfully(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir

        client._save_commit_hash("abc123")

        config = json.loads((content_dir / ".agblogger.json").read_text())
        assert config["last_sync_commit"] == "abc123"


class TestGetLastSyncCommitCorruptConfigWarning:
    """Issue 3: Corrupt config warning must explain that merge will be degraded."""

    def test_corrupt_config_warning_mentions_merge_degradation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Write corrupted config
        (content_dir / ".agblogger.json").write_text("NOT VALID JSON {{{")

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir

        result = client._get_last_sync_commit()

        assert result is None
        captured = capsys.readouterr()
        # Warning must mention merge degradation consequences
        assert "merge" in captured.err.lower() or "server version" in captured.err.lower()


class TestSaveCommitHashFailureWarning:
    """Issue 4: Failed commit hash save warning must explain consequences."""

    def test_save_commit_hash_failure_warns_about_next_sync(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Make the content dir read-only so save_config fails
        config_path = content_dir / ".agblogger.json"
        config_path.write_text("{}")
        config_path.chmod(stat.S_IRUSR)  # read-only for owner

        client = SyncClient.__new__(SyncClient)
        client.content_dir = content_dir

        try:
            client._save_commit_hash("abc123")
        finally:
            # Restore permissions so tmp_path cleanup works
            config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        captured = capsys.readouterr()
        # Warning must explain consequence: next sync may produce incorrect results
        warning = captured.err.lower()
        assert "warning" in warning
        assert "next sync" in warning or "incorrect" in warning or "merge" in warning


class TestSyncCommitServerErrorDetail:
    """Issue 5: Server error detail from JSON body should be shown to the user."""

    def test_sync_commit_http_error_shows_server_detail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        plan: dict[str, list[object]] = {
            "to_upload": [],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": [],
            "conflicts": [],
        }

        request = httpx.Request("POST", "http://localhost:8000/api/sync/commit")
        error_response = httpx.Response(
            status_code=507,
            json={"detail": "Storage limit reached"},
            request=request,
        )
        http_error = httpx.HTTPStatusError(
            "507 Insufficient Storage",
            request=request,
            response=error_response,
        )

        mock_request = MagicMock()
        mock_request.raise_for_status.side_effect = http_error

        with (
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_request", return_value=mock_request),
            patch("cli.sync_client.scan_local_files", return_value={}),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()

            client.sync(plan)

        captured = capsys.readouterr()
        assert "Storage limit reached" in captured.out


class TestSyncLocalDeleteOSError:
    """Issue 6: OSError during local file deletion must warn and continue, not crash."""

    def test_delete_local_permission_error_warns_and_continues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Create two files: one unlink will fail, one will succeed
        (content_dir / "good.md").write_text("good")
        (content_dir / "bad.md").write_text("bad")

        plan = {
            "to_upload": [],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": ["bad.md", "good.md"],
            "conflicts": [],
        }
        commit_response = {
            "to_download": [],
            "conflicts": [],
            "warnings": [],
            "commit_hash": "abc123",
        }

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = commit_response

        original_unlink = Path.unlink

        def selective_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.name == "bad.md":
                raise PermissionError(f"Permission denied: {self}")
            original_unlink(self, missing_ok=missing_ok)

        with (
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_save_commit_hash"),
            patch("cli.sync_client.scan_local_files", return_value={}),
            patch("cli.sync_client.save_manifest"),
            patch.object(Path, "unlink", selective_unlink),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()
            client.client.post.return_value = mock_post

            # Must not crash
            client.sync(plan)

        captured = capsys.readouterr()
        # A warning should mention bad.md
        assert "Warning" in captured.out or "warning" in captured.out.lower()
        assert "bad.md" in captured.out

        # good.md should be counted (was successfully deleted), bad.md should not
        assert "1 file(s) synced" in captured.out


class TestDownloadFileWriteBytesOSError:
    """Issue 7: OSError in write_bytes during download must return False, not crash."""

    def test_download_file_returns_false_on_write_oserror(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"file content"

        with (
            patch.object(SyncClient, "_request", return_value=mock_resp),
            patch.object(Path, "write_bytes", side_effect=OSError("No space left on device")),
            patch.object(Path, "mkdir"),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()

            result = client._download_file("posts/test/index.md")

        assert result is False
        captured = capsys.readouterr()
        assert "ERROR" in captured.out or "error" in captured.out.lower()


class TestUploadFileReadBytesOSError:
    """Issue 8: OSError in read_bytes during upload must skip file with warning, not crash."""

    def test_unreadable_upload_file_skipped_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Create one unreadable file and one readable file
        bad_file = content_dir / "bad.md"
        bad_file.write_text("bad")
        good_file = content_dir / "good.md"
        good_file.write_text("good")

        plan = {
            "to_upload": ["bad.md", "good.md"],
            "to_download": [],
            "to_delete_remote": [],
            "to_delete_local": [],
            "conflicts": [],
        }
        commit_response = {
            "to_download": [],
            "conflicts": [],
            "warnings": [],
            "commit_hash": "abc123",
        }

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = commit_response

        original_read_bytes = Path.read_bytes

        def selective_read_bytes(self: Path) -> bytes:
            if self.name == "bad.md":
                raise PermissionError(f"Permission denied: {self}")
            return original_read_bytes(self)

        with (
            patch.object(SyncClient, "_get_last_sync_commit", return_value=None),
            patch.object(SyncClient, "_save_commit_hash"),
            patch("cli.sync_client.scan_local_files", return_value={}),
            patch("cli.sync_client.save_manifest"),
            patch.object(Path, "read_bytes", selective_read_bytes),
        ):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()
            client.client.post.return_value = mock_post

            # Must not crash
            client.sync(plan)

        captured = capsys.readouterr()
        # Should warn about bad.md
        assert "bad.md" in captured.out
        assert "Warning" in captured.out or "warning" in captured.out.lower()
        # Should still upload good.md (1 file synced)
        assert "1 file(s) synced" in captured.out


class TestBackupCleanupOSErrorWarning:
    """Issue 16: OSError during backup cleanup should print a warning, not silently swallow."""

    def test_backup_cleanup_oserror_warns_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # No local files for any conflict path — backed_up will be 0,
        # so cleanup is triggered. We make shutil.rmtree raise OSError.
        conflicts = [{"file_path": "posts/missing/index.md"}]

        with patch("cli.sync_client.shutil.rmtree", side_effect=OSError("busy")):
            client = SyncClient.__new__(SyncClient)
            client.content_dir = content_dir
            client.server_url = "http://localhost:8000"
            client.client = MagicMock()

            client._backup_conflicted_files(conflicts)

        captured = capsys.readouterr()
        assert "Warning" in captured.err or "warning" in captured.err.lower()
