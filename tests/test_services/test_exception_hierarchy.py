"""Tests for exception class hierarchy and error handling fixes.

Covers:
- OAuth error classes extend ExternalServiceError
- DuplicateAccountError extends a handled type
- git_service.init_repo catches TimeoutExpired
- Pandoc retry preserves exception chain
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.exceptions import ExternalServiceError

if TYPE_CHECKING:
    from pathlib import Path


class TestOAuthErrorHierarchy:
    """OAuth error classes must extend ExternalServiceError for safety net."""

    def test_atproto_oauth_error_is_external_service_error(self) -> None:
        from backend.crosspost.atproto_oauth import ATProtoOAuthError

        exc = ATProtoOAuthError("test error")
        assert isinstance(exc, ExternalServiceError)

    def test_mastodon_oauth_error_is_external_service_error(self) -> None:
        from backend.crosspost.mastodon import MastodonOAuthTokenError

        exc = MastodonOAuthTokenError("test error")
        assert isinstance(exc, ExternalServiceError)

    def test_x_oauth_error_is_external_service_error(self) -> None:
        from backend.crosspost.x import XOAuthTokenError

        exc = XOAuthTokenError("test error")
        assert isinstance(exc, ExternalServiceError)

    def test_facebook_oauth_error_is_external_service_error(self) -> None:
        from backend.crosspost.facebook import FacebookOAuthTokenError

        exc = FacebookOAuthTokenError("test error")
        assert isinstance(exc, ExternalServiceError)


class TestDuplicateAccountErrorHierarchy:
    """DuplicateAccountError must extend ValueError for the global handler."""

    def test_duplicate_account_error_is_value_error(self) -> None:
        from backend.services.crosspost_service import DuplicateAccountError

        exc = DuplicateAccountError("already exists")
        assert isinstance(exc, ValueError)


class TestGitServiceInitRepoTimeoutExpired:
    """init_repo must catch TimeoutExpired, not just CalledProcessError."""

    async def test_init_repo_catches_timeout_expired(self, tmp_path: Path) -> None:
        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=subprocess.TimeoutExpired(cmd=["git", "init"], timeout=30),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs.init_repo()

    async def test_init_repo_logs_timeout_expired(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=subprocess.TimeoutExpired(cmd=["git", "init"], timeout=30),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs.init_repo()

        assert any("git" in r.message.lower() for r in caplog.records)


class TestGitServiceInitRepoOSError:
    """init_repo must catch OSError (superset of FileNotFoundError)."""

    async def test_init_repo_catches_permission_error(self, tmp_path: Path) -> None:
        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=PermissionError(13, "permission denied"),
            ),
            pytest.raises(PermissionError),
        ):
            await gs.init_repo()

    async def test_init_repo_logs_permission_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=PermissionError(13, "permission denied"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(PermissionError),
        ):
            await gs.init_repo()

        assert any("git" in r.message.lower() for r in caplog.records)


class TestPandocRetryPreservesExceptionChain:
    """Pandoc retry must preserve the exception chain, not discard with `from None`."""

    async def test_retry_exception_has_cause(self) -> None:
        import httpx

        from backend.pandoc.renderer import RenderError, _render_markdown, _sanitize_html

        mock_server = AsyncMock()
        mock_server.base_url = "http://localhost:9999"
        mock_server.ensure_running = AsyncMock()

        original_error = OSError("broken pipe")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[httpx.NetworkError("conn reset"), original_error])

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
        ):
            with pytest.raises(RenderError) as exc_info:
                await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)

            # The __cause__ should be the retry exception, not None
            assert exc_info.value.__cause__ is not None
