"""Tests for global exception handlers covering unhandled exception types.

Covers:
- subprocess.TimeoutExpired → 502 with generic message (no command leak)
- IntegrityError → 500 with generic message (no SQL leak)
- KeyError → 500 with generic message (no key leak)
- DuplicateAccountError caught by global handler as safety net
- OAuth error classes caught by ExternalServiceError global handler
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
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


class TestTimeoutExpiredGlobalHandler:
    """subprocess.TimeoutExpired must return 502 with generic message, not leak command."""

    async def test_timeout_expired_returns_502_generic_message(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=subprocess.TimeoutExpired(
                cmd=["git", "commit", "-m", "secret"],
                timeout=30,
            ),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 502
        body = resp.json()
        assert "git" not in body["detail"].lower()
        assert "secret" not in body["detail"].lower()
        assert "timeout" in body["detail"].lower() or "process" in body["detail"].lower()

    async def test_timeout_expired_does_not_leak_command(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=subprocess.TimeoutExpired(
                cmd=["git", "--secret-flag", "/internal/path"],
                timeout=30,
            ),
        ):
            resp = await client.get("/api/posts", headers=headers)

        body = resp.json()
        assert "/internal/path" not in body["detail"]
        assert "--secret-flag" not in body["detail"]


class TestIntegrityErrorGlobalHandler:
    """IntegrityError must return 409 with generic message, not leak SQL."""

    async def test_integrity_error_returns_409_generic_message(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=IntegrityError("UNIQUE constraint failed: users.username", {}, Exception()),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 409
        body = resp.json()
        assert "UNIQUE" not in body["detail"]
        assert "users.username" not in body["detail"]

    async def test_integrity_error_does_not_leak_sql(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=IntegrityError(
                "INSERT INTO secret_table (col) VALUES (?)", {}, Exception()
            ),
        ):
            resp = await client.get("/api/posts", headers=headers)

        body = resp.json()
        assert "secret_table" not in body["detail"]
        assert "INSERT" not in body["detail"]


class TestKeyErrorGlobalHandler:
    """KeyError must return 500 with generic message, not leak key name."""

    async def test_key_error_returns_500_generic_message(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=KeyError("internal_secret_key"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 500
        body = resp.json()
        assert "internal_secret_key" not in body["detail"]


class TestOAuthErrorsSafetyNet:
    """OAuth error classes must be caught by ExternalServiceError global handler."""

    async def test_atproto_oauth_error_returns_502(self, client: AsyncClient) -> None:
        from backend.crosspost.atproto_oauth import ATProtoOAuthError

        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=ATProtoOAuthError("token expired: secret_token_xyz"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 502
        body = resp.json()
        assert "secret_token_xyz" not in body["detail"]

    async def test_mastodon_oauth_error_returns_502(self, client: AsyncClient) -> None:
        from backend.crosspost.mastodon import MastodonOAuthTokenError

        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=MastodonOAuthTokenError("HTTP 401: invalid_grant"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 502
        body = resp.json()
        assert "401" not in body["detail"]

    async def test_x_oauth_error_returns_502(self, client: AsyncClient) -> None:
        from backend.crosspost.x import XOAuthTokenError

        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=XOAuthTokenError("rate limited"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 502
        body = resp.json()
        assert "rate limited" not in body["detail"]

    async def test_facebook_oauth_error_returns_502(self, client: AsyncClient) -> None:
        from backend.crosspost.facebook import FacebookOAuthTokenError

        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=FacebookOAuthTokenError("access token invalid"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        assert resp.status_code == 502
        body = resp.json()
        assert "access token" not in body["detail"]


class TestDuplicateAccountErrorSafetyNet:
    """DuplicateAccountError must be caught by a global handler."""

    async def test_duplicate_account_error_returns_409(self, client: AsyncClient) -> None:
        from backend.services.crosspost_service import DuplicateAccountError

        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=DuplicateAccountError("Account already exists for bluesky/myhandle"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        # Should be caught by ValueError handler (409 or 422), not 500
        assert resp.status_code != 500
