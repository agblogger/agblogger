"""Integration tests for analytics API endpoints."""

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
    """Create settings for test app."""
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


async def _get_admin_token(client: AsyncClient) -> str:
    """Obtain a valid admin Bearer token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_and_login(client: AsyncClient, username: str, password: str) -> str:
    """Register a non-admin user and return their token."""
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert resp.status_code in {200, 201}, resp.text
    resp2 = await client.post(
        "/api/auth/token-login",
        json={"username": username, "password": password},
    )
    assert resp2.status_code == 200
    return resp2.json()["access_token"]


class TestAnalyticsAdminAuth:
    """Verify admin auth gates on all admin analytics endpoints."""

    @pytest.mark.asyncio
    async def test_get_settings_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/settings")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_settings_non_admin(self, client: AsyncClient) -> None:
        token = await _register_and_login(client, "regular", "password123")
        resp = await client.get(
            "/api/admin/analytics/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_put_settings_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_put_settings_non_admin(self, client: AsyncClient) -> None:
        token = await _register_and_login(client, "regular2", "password123")
        resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_total_stats_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/total")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_path_hits_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/hits")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_path_referrers_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/hits/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_breakdown_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/browsers")
        assert resp.status_code == 401


class TestAnalyticsSettings:
    """Tests for analytics settings GET and PUT endpoints."""

    @pytest.mark.asyncio
    async def test_get_settings_returns_defaults(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "analytics_enabled" in data
        assert "show_views_on_posts" in data
        # defaults from service layer
        assert data["analytics_enabled"] is True
        assert data["show_views_on_posts"] is False

    @pytest.mark.asyncio
    async def test_put_settings_updates_analytics_enabled(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["analytics_enabled"] is False

    @pytest.mark.asyncio
    async def test_put_settings_persists(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        # Update show_views_on_posts to True
        put_resp = await client.put(
            "/api/admin/analytics/settings",
            json={"show_views_on_posts": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["show_views_on_posts"] is True

        # Verify it was persisted by reading back
        get_resp = await client.get(
            "/api/admin/analytics/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["show_views_on_posts"] is True

    @pytest.mark.asyncio
    async def test_put_settings_partial_update(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        # Set initial state
        await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": True, "show_views_on_posts": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Update only analytics_enabled
        put_resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert put_resp.status_code == 200
        data = put_resp.json()
        assert data["analytics_enabled"] is False
        # show_views_on_posts should remain unchanged
        assert data["show_views_on_posts"] is False


class TestAnalyticsStatsProxy:
    """Tests for admin stats proxy endpoints (mocked GoatCounter)."""

    @pytest.mark.asyncio
    async def test_total_stats_returns_zeros_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_views"] == 0
        assert data["total_unique"] == 0

    @pytest.mark.asyncio
    async def test_path_hits_returns_empty_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paths"] == []

    @pytest.mark.asyncio
    async def test_path_referrers_returns_empty_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits/42",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path_id"] == 42
        assert data["referrers"] == []

    @pytest.mark.asyncio
    async def test_breakdown_returns_empty_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "browsers"
        assert data["entries"] == []

    @pytest.mark.asyncio
    async def test_breakdown_rejects_invalid_category(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/invalid_category",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "Unknown analytics category" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_total_stats_accepts_date_params(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "2024-01-01", "end": "2024-12-31"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestPublicViewCount:
    """Tests for the public view count endpoint."""

    @pytest.mark.asyncio
    async def test_view_count_returns_null_when_setting_disabled(self, client: AsyncClient) -> None:
        # Default: show_views_on_posts=False → fetch_view_count returns None
        resp = await client.get("/api/analytics/views/some-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] is None

    @pytest.mark.asyncio
    async def test_view_count_returns_null_for_nonexistent_post_when_disabled(
        self, client: AsyncClient
    ) -> None:
        # Same result for non-existent paths — no info disclosure
        resp = await client.get("/api/analytics/views/does-not-exist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] is None

    @pytest.mark.asyncio
    async def test_view_count_returns_count_when_enabled(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        # Enable show_views_on_posts
        await client.put(
            "/api/admin/analytics/settings",
            json={"show_views_on_posts": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Mock GoatCounter response
        mock_data: dict[str, list[dict[str, object]]] = {
            "hits": [{"path": "/post/my-post", "count": 42, "count_unique": 30}]
        }
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ):
            resp = await client.get("/api/analytics/views/my-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] == 42

    @pytest.mark.asyncio
    async def test_view_count_returns_zero_for_unknown_path_when_enabled(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        # Enable show_views_on_posts
        await client.put(
            "/api/admin/analytics/settings",
            json={"show_views_on_posts": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Path not in GoatCounter response
        mock_data: dict[str, list[dict[str, object]]] = {"hits": []}
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ):
            resp = await client.get("/api/analytics/views/unknown-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] == 0

    @pytest.mark.asyncio
    async def test_view_count_is_public_no_auth_required(self, client: AsyncClient) -> None:
        # No auth header — should succeed (public endpoint)
        resp = await client.get("/api/analytics/views/any-post")
        assert resp.status_code == 200
