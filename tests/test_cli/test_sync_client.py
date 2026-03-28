"""Tests for CLI sync client."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from cli.sync_client import SyncClient, validate_server_url

if TYPE_CHECKING:
    from pathlib import Path


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
