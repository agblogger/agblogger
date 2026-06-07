"""Tests for CLI credential storage."""

from __future__ import annotations

import json
import stat
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agblogger_cli.credentials import (
    delete_credentials,
    load_credentials,
    revoke_session,
    save_credentials,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestLoadCredentials:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_returns_none_for_unknown_server(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text(
            json.dumps({"https://other.example.com": {"username": "admin", "refresh_token": "tok"}})
        )
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_returns_credentials_for_known_server(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        payload = {"https://blog.example.com": {"username": "admin", "refresh_token": "mytoken"}}
        creds_path.write_text(json.dumps(payload))
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["username"] == "admin"
        assert result["refresh_token"] == "mytoken"

    def test_returns_none_on_malformed_json(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("not-json{{{")
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_returns_none_when_json_is_not_a_dict(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("[]")
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None


class TestSaveCredentials:
    def test_round_trip(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["username"] == "admin"
        assert result["refresh_token"] == "mytoken"

    _posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")

    @_posix_only
    def test_sets_restrictive_permissions(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
        mode = stat.S_IMODE(creds_path.stat().st_mode)
        assert mode == 0o600

    def test_multiple_servers_coexist(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog1.example.com", "admin", "token1")
            save_credentials("https://blog2.example.com", "admin", "token2")
            r1 = load_credentials("https://blog1.example.com")
            r2 = load_credentials("https://blog2.example.com")
        assert r1 is not None and r1["refresh_token"] == "token1"
        assert r2 is not None and r2["refresh_token"] == "token2"

    def test_overwrites_existing_entry(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "old-token")
            save_credentials("https://blog.example.com", "admin", "new-token")
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["refresh_token"] == "new-token"


class TestDeleteCredentials:
    def test_removes_entry(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
            delete_credentials("https://blog.example.com")
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_leaves_other_servers_intact(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog1.example.com", "admin", "token1")
            save_credentials("https://blog2.example.com", "admin", "token2")
            delete_credentials("https://blog1.example.com")
            result = load_credentials("https://blog2.example.com")
        assert result is not None
        assert result["refresh_token"] == "token2"

    def test_no_error_when_server_not_present(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            delete_credentials("https://blog.example.com")  # should not raise


class TestRevokeSession:
    def test_posts_refresh_token_to_logout_endpoint(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        with patch("agblogger_cli.credentials.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            revoke_session("https://blog.example.com", "mytoken")
        mock_client.post.assert_called_once_with(
            "/api/auth/logout",
            json={"refresh_token": "mytoken"},
        )
        mock_httpx.Client.assert_called_once_with(base_url="https://blog.example.com", timeout=10.0)

    def test_prints_warning_on_http_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agblogger_cli.credentials.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
            mock_httpx.HTTPError = httpx.HTTPError
            request = httpx.Request("POST", "https://blog.example.com/api/auth/logout")
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "server error",
                request=request,
                response=httpx.Response(status_code=500, request=request),
            )
            revoke_session("https://blog.example.com", "mytoken")
        captured = capsys.readouterr()
        assert "Warning" in captured.err
