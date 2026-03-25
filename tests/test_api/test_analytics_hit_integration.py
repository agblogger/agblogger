"""Integration tests for analytics hit recording in post and page endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings with a sample post and page for hit recording tests."""
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n# Hello World\n\nTest content.\n"
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
    """Create test HTTP client."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _get_admin_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestPostHitRecording:
    """Verify hit recording is triggered (or skipped) on GET /api/posts/{slug}."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_fires_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.api.posts.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/hello")
            assert resp.status_code == 200
            # Allow the background task to run
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/post/hello"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_authenticated_request_skips_hit(self, client: AsyncClient) -> None:
        import asyncio

        token = await _get_admin_token(client)
        with patch(
            "backend.api.posts.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get(
                "/api/posts/hello",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            await asyncio.sleep(0)
        # record_hit is still called but the service itself skips authenticated users.
        # We verify the user argument is NOT None (so the service can make that decision).
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["user"] is not None

    @pytest.mark.asyncio
    async def test_hit_recorded_with_correct_path(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.api.posts.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/posts/hello/index.md")
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/post/hello"

    @pytest.mark.asyncio
    async def test_nonexistent_post_does_not_fire_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.api.posts.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/does-not-exist")
            assert resp.status_code == 404
            await asyncio.sleep(0)
        mock_record.assert_not_called()


class TestPageHitRecording:
    """Verify hit recording is triggered on GET /api/pages/{page_id}."""

    @pytest.mark.asyncio
    async def test_unauthenticated_page_request_fires_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.api.pages.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/pages/timeline")
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/page/timeline"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_authenticated_page_request_passes_user_to_record_hit(
        self, client: AsyncClient
    ) -> None:
        import asyncio

        token = await _get_admin_token(client)
        with patch(
            "backend.api.pages.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get(
                "/api/pages/timeline",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["user"] is not None

    @pytest.mark.asyncio
    async def test_nonexistent_page_does_not_fire_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.api.pages.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/pages/does-not-exist")
            assert resp.status_code == 404
            await asyncio.sleep(0)
        mock_record.assert_not_called()
