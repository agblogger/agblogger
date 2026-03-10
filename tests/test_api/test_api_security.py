"""API-level tests for security fixes (Issues 3, 6, 13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
    # Write an about page
    (tmp_content_dir / "about.md").write_text("# About\n\nThis is the about page.\n")
    (tmp_content_dir / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
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
        auth_self_registration=True,
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(app_settings) as ac:
        yield ac


class TestPageIdValidation:
    """Issue 3: Page ID must be validated against path traversal."""

    @pytest.mark.asyncio
    async def test_valid_page_id(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/about")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/../../etc/passwd")
        # The request must not succeed and must not cause a server error
        assert resp.status_code != 200
        assert resp.status_code < 500

    @pytest.mark.asyncio
    async def test_dots_in_page_id_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/test..page")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_slash_in_page_id_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/test/page")
        # The request must not succeed and must not cause a server error
        assert resp.status_code != 200
        assert resp.status_code < 500

    @pytest.mark.asyncio
    async def test_special_chars_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/test%20page")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_hyphen_underscore_allowed(self, client: AsyncClient) -> None:
        # This page doesn't exist but the ID is valid format
        resp = await client.get("/api/pages/my-page_1")
        assert resp.status_code == 404  # Valid ID, but page not found


class TestCrosspostHistoryAuth:
    """Issue 6: Crosspost history endpoint should require authentication."""

    @pytest.mark.asyncio
    async def test_history_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/crosspost/history/posts/hello.md")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_history_with_auth_works(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/crosspost/history/posts/hello.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestAuthTokenValidation:
    """Issue 13: Invalid JWT sub values should not crash the server."""

    @pytest.mark.asyncio
    async def test_malformed_bearer_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer garbage-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, client: AsyncClient) -> None:
        from backend.services.auth_service import create_access_token

        # Create a token that expires immediately (negative minutes)
        token = create_access_token(
            {"sub": "1", "username": "admin", "is_admin": True},
            "test-secret-key-with-at-least-32-characters",
            expires_minutes=-1,
        )
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


class TestAuthLogout:
    """Logout should revoke refresh tokens server-side."""

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        csrf_token = login_resp.json()["csrf_token"]
        refresh_token = client.cookies.get("refresh_token")
        assert refresh_token is not None

        logout_resp = await client.post(
            "/api/auth/logout",
            json={"refresh_token": refresh_token},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert logout_resp.status_code == 204

        refresh_resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_with_unknown_token_returns_204(self, client: AsyncClient) -> None:
        logout_resp = await client.post(
            "/api/auth/logout",
            json={"refresh_token": "not-a-real-refresh-token"},
        )
        assert logout_resp.status_code == 204


class TestLabelCreateEmptyNames:
    """Issue 32: Creating labels with empty names should be rejected."""

    @pytest.mark.asyncio
    async def test_create_label_empty_names_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/labels",
            json={"id": "test-empty", "names": [""]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_label_whitespace_names_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/labels",
            json={"id": "test-ws", "names": ["   "]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
