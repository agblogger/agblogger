"""Tests for git commit warning header and crosspost status fallback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.crosspost import _safe_status
from backend.config import Settings
from backend.schemas.crosspost import CrossPostStatus
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


class TestSafeStatus:
    def test_valid_status_returned(self) -> None:
        assert _safe_status("posted") == CrossPostStatus.POSTED
        assert _safe_status("pending") == CrossPostStatus.PENDING
        assert _safe_status("failed") == CrossPostStatus.FAILED

    def test_unknown_status_returns_unknown(self) -> None:
        result = _safe_status("bogus")
        assert result == CrossPostStatus.UNKNOWN

    def test_unknown_status_logs_at_error_level(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger="backend.api.crosspost"):
            _safe_status("bogus")
        assert any("Unknown cross-post status" in r.message for r in caplog.records)
        assert any(r.levelno == logging.ERROR for r in caplog.records)


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ntitle: Hello\ncreated_at: 2026-01-01 00:00:00+00:00\n"
        "modified_at: 2026-01-01 00:00:00+00:00\nauthor: admin\n"
        "labels: []\n---\nHello\n"
    )
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings) as ac:
        yield ac


class TestGitWarningHeader:
    @pytest.mark.asyncio
    async def test_create_post_sets_git_warning_on_commit_failure(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        with patch(
            "backend.services.git_service.GitService.try_commit",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": "Test Post",
                    "body": "Body content",
                    "labels": [],
                    "is_draft": False,
                },
                headers=headers,
            )
        assert resp.status_code == 201
        assert resp.headers.get("X-Git-Warning") is not None
