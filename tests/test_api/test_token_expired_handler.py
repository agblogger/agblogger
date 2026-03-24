"""Tests for global TokenExpiredError exception handler.

Ensures that TokenExpiredError raised anywhere in the application
is caught by a global handler and returns HTTP 401 with appropriate message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.config import Settings
from backend.exceptions import TokenExpiredError
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\n---\n# Hello World\n\nTest content.\n"
    )
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


async def _login(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


class TestTokenExpiredGlobalHandler:
    """TokenExpiredError must return 401 with appropriate message."""

    async def test_token_expired_returns_401(self, client: AsyncClient) -> None:
        """TokenExpiredError raised in endpoint should return 401."""
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=TokenExpiredError("Personal access token expired"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 401
        body = resp.json()
        assert "expired" in body["detail"].lower()

    async def test_token_expired_does_not_leak_internal_details(self, client: AsyncClient) -> None:
        """TokenExpiredError response should not leak internal token details."""
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=TokenExpiredError("Token abc123secret expired at 2026-01-01"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 401
        body = resp.json()
        assert "abc123secret" not in body["detail"]

    async def test_token_expired_does_not_log_exception_message(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """TokenExpiredError logs should avoid exception text that may contain secrets."""
        headers = await _login(client)
        with (
            patch(
                "backend.api.posts.list_posts",
                new_callable=AsyncMock,
                side_effect=TokenExpiredError("Token abc123secret expired at 2026-01-01"),
            ),
            caplog.at_level(logging.WARNING, logger="backend.main"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 401
        warning_messages = [
            record.message for record in caplog.records if record.levelno == logging.WARNING
        ]
        assert any(
            message == "Expired auth rejected for GET /api/posts" for message in warning_messages
        )
        assert all("abc123secret" not in message for message in warning_messages)
