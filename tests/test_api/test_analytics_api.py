"""Integration tests for analytics API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from backend.api.analytics import _resolve_public_post_slug
from backend.config import Settings
from backend.models.base import CacheBase
from backend.models.post import PostCache
from backend.schemas.analytics import (
    AnalyticsSettingsUpdate,
    BreakdownEntry,
    PathHit,
    PathReferrersResponse,
    TotalStatsResponse,
)
from backend.utils.slug import file_path_to_slug
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


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


async def _enable_post_views(client: AsyncClient, headers: dict[str, str]) -> None:
    """Enable public post view counts."""
    resp = await client.put(
        "/api/admin/analytics/settings",
        json={"show_views_on_posts": True},
        headers=headers,
    )
    assert resp.status_code == 200


async def _create_published_post(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "Analytics public post",
    body: str = "Body text\n",
) -> tuple[str, str]:
    """Create a published post and return (file_path, slug)."""
    create_resp = await client.post(
        "/api/posts",
        json={
            "title": title,
            "body": body,
            "is_draft": False,
            "labels": [],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    file_path = create_resp.json()["file_path"]
    return file_path, file_path_to_slug(file_path)


class TestAnalyticsAdminAuth:
    """Verify admin auth gates on all admin analytics endpoints."""

    @pytest.mark.asyncio
    async def test_get_settings_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/settings")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_put_settings_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
        )
        assert resp.status_code == 401

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


class TestNewAnalyticsEndpoints:
    """Tests for new analytics endpoints (dashboard parity)."""

    @pytest.mark.asyncio
    async def test_views_over_time_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/views-over-time")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_site_referrers_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/referrers")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_breakdown_detail_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/browsers/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_create_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.post("/api/admin/analytics/export")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_status_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/export/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_download_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/export/1/download")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_views_over_time_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/views-over-time",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_site_referrers_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/referrers",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_breakdown_detail_invalid_category(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/locations/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_breakdown_detail_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_breakdown_detail",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/browsers/chrome",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503


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
    async def test_total_stats_returns_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        # GoatCounter is not running in tests; service returns None → 503
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_path_hits_returns_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_path_referrers_returns_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits/42",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_breakdown_returns_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_breakdown_rejects_invalid_category(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/invalid_category",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Literal type validation returns 422
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_total_stats_accepts_date_params(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "2024-01-01", "end": "2024-12-31"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 503 because GoatCounter not running in tests, but not 422
        assert resp.status_code in {200, 503}


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
    async def test_view_count_returns_null_when_analytics_disabled_even_if_post_views_enabled(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False, "show_views_on_posts": True},
            headers=headers,
        )
        _, slug = await _create_published_post(client, headers, title="Analytics disabled post")

        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": [{"path": f"/post/{slug}", "count": 42}]}),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{slug}")

        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_req.assert_not_called()

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
        headers = {"Authorization": f"Bearer {token}"}
        await _enable_post_views(client, headers)
        _, slug = await _create_published_post(client, headers, title="Analytics visible post")
        # Mock GoatCounter response
        mock_data: dict[str, list[dict[str, object]]] = {
            "hits": [{"path": f"/post/{slug}", "count": 42}]
        }
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ):
            resp = await client.get(f"/api/analytics/views/{slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] == 42

    @pytest.mark.asyncio
    async def test_view_count_returns_zero_for_unknown_path_when_enabled(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _enable_post_views(client, headers)
        _, slug = await _create_published_post(client, headers, title="Analytics zero post")
        # Published post exists, but GoatCounter has no hit row for it.
        mock_data: dict[str, list[dict[str, object]]] = {"hits": []}
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ):
            resp = await client.get(f"/api/analytics/views/{slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["views"] == 0

    @pytest.mark.asyncio
    async def test_view_count_is_public_no_auth_required(self, client: AsyncClient) -> None:
        # No auth header — should succeed (public endpoint)
        resp = await client.get("/api/analytics/views/any-post")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_view_count_returns_null_for_post_drafted_after_publication(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "title": "Public analytics regression",
            "body": "Body text\n",
            "is_draft": False,
            "labels": [],
        }

        await _enable_post_views(client, headers)
        create_resp = await client.post("/api/posts", json=body, headers=headers)
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]
        slug = file_path_to_slug(file_path)

        draft_resp = await client.put(
            f"/api/posts/{file_path}",
            json={**body, "is_draft": True},
            headers=headers,
        )
        assert draft_resp.status_code == 200

        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": [{"path": f"/post/{slug}", "count": 42}]}),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{slug}")

        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_view_count_returns_null_for_deleted_post_with_historical_hits(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "title": "Delete analytics regression",
            "body": "Body text\n",
            "is_draft": False,
            "labels": [],
        }

        await _enable_post_views(client, headers)
        create_resp = await client.post("/api/posts", json=body, headers=headers)
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]
        slug = file_path_to_slug(file_path)

        delete_resp = await client.delete(f"/api/posts/{file_path}", headers=headers)
        assert delete_resp.status_code == 204

        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": [{"path": f"/post/{slug}", "count": 42}]}),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{slug}")

        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_req.assert_not_called()


class TestStatsServiceUnavailable:
    """Tests for 503 when stats service functions return None."""

    @pytest.mark.asyncio
    async def test_total_stats_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_total_stats",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/total",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_path_hits_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_path_hits",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/hits",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_path_referrers_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_path_referrers",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/hits/7",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_breakdown_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_breakdown",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/browsers",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_total_stats_returns_503_without_reaching_goatcounter_when_analytics_disabled(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        update_resp = await client.put(
            "/api/admin/analytics/settings",
            json={"analytics_enabled": False},
            headers=headers,
        )
        assert update_resp.status_code == 200

        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"total": 1}),
        ) as mock_req:
            resp = await client.get(
                "/api/admin/analytics/stats/total",
                headers=headers,
            )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_views_over_time_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_views_over_time",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/views-over-time",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_site_referrers_returns_503_when_service_none(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_site_referrers",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/referrers",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"

    @pytest.mark.asyncio
    async def test_breakdown_detail_returns_503_when_service_none(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_breakdown_detail",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/browsers/chrome",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"


class TestDateParameterValidation:
    """Tests for analytics range parameter validation."""

    @pytest.mark.asyncio
    async def test_total_stats_rejects_invalid_start_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "invalid"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_total_stats_rejects_invalid_end_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"end": "not-a-date"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_total_stats_accepts_valid_date_format(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "2024-01-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 200 or 503 (GoatCounter not running), but not 422
        assert resp.status_code in {200, 503}

    @pytest.mark.asyncio
    async def test_total_stats_accepts_valid_datetime_format(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "2024-01-01T00:00:00.000Z", "end": "2024-01-31T23:59:59.999Z"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 200 or 503 (GoatCounter not running), but not 422
        assert resp.status_code in {200, 503}

    @pytest.mark.asyncio
    async def test_path_hits_rejects_invalid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits",
            params={"start": "01-01-2024"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_path_hits_accepts_valid_datetime(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits",
            params={"start": "2024-01-01T00:00:00.000Z"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in {200, 503}

    @pytest.mark.asyncio
    async def test_breakdown_rejects_invalid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers",
            params={"start": "2024/01/01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_breakdown_accepts_valid_datetime(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers",
            params={"end": "2024-01-31T23:59:59.999Z"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in {200, 503}

    @pytest.mark.asyncio
    async def test_views_over_time_rejects_invalid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/views-over-time",
            params={"start": "invalid"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_referrers_rejects_invalid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/referrers",
            params={"start": "01-01-2024"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_views_over_time_accepts_valid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/views-over-time",
            params={"start": "2024-01-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in {200, 503}

    @pytest.mark.asyncio
    async def test_referrers_accepts_valid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/referrers",
            params={"end": "2024-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in {200, 503}


class TestSchemaValidation:
    """Tests for Pydantic ge=0 constraints on count fields."""

    def test_total_stats_rejects_negative_visitors(self) -> None:
        with pytest.raises(ValidationError):
            TotalStatsResponse(visitors=-1)

    def test_total_stats_accepts_zero(self) -> None:
        resp = TotalStatsResponse(visitors=0)
        assert resp.visitors == 0

    def test_breakdown_entry_rejects_negative_count(self) -> None:
        with pytest.raises(ValidationError):
            BreakdownEntry(name="Chrome", count=-1, percent=50.0)

    def test_breakdown_entry_rejects_percent_over_100(self) -> None:
        with pytest.raises(ValidationError):
            BreakdownEntry(name="Chrome", count=0, percent=101.0)

    def test_breakdown_entry_rejects_negative_percent(self) -> None:
        with pytest.raises(ValidationError):
            BreakdownEntry(name="Chrome", count=0, percent=-1.0)

    def test_breakdown_entry_accepts_valid(self) -> None:
        entry = BreakdownEntry(name="Chrome", count=10, percent=50.0)
        assert entry.count == 10
        assert entry.percent == 50.0


class TestBreakdownCategoryLiteral:
    """Tests for Literal type validation on breakdown category path parameter."""

    @pytest.mark.asyncio
    async def test_breakdown_rejects_invalid_category_returns_422(
        self, client: AsyncClient
    ) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/invalid_category",
            headers={"Authorization": f"Bearer {token}"},
        )
        # With Literal type validation, FastAPI returns 422
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_breakdown_accepts_all_valid_categories(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        valid_categories = ["browsers", "systems", "languages", "locations", "sizes", "campaigns"]
        for category in valid_categories:
            with patch(
                "backend.api.analytics.fetch_breakdown",
                new=AsyncMock(return_value=None),
            ):
                resp = await client.get(
                    f"/api/admin/analytics/stats/{category}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            # 503 because we mocked None — but not 422/400
            assert resp.status_code == 503, (
                f"Expected 503 for category={category}, got {resp.status_code}"
            )


class TestAnalyticsSettingsUpdateValidator:
    """Tests for the empty-payload model validator on AnalyticsSettingsUpdate."""

    @pytest.mark.asyncio
    async def test_put_settings_empty_payload_returns_422(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.put(
            "/api/admin/analytics/settings",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestAnalyticsSettingsUpdateSchemaLevel:
    """Issue 10: Direct schema-level tests for AnalyticsSettingsUpdate validator."""

    def test_empty_body_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            AnalyticsSettingsUpdate()

    def test_with_one_field_succeeds(self) -> None:
        obj = AnalyticsSettingsUpdate(analytics_enabled=True)
        assert obj.analytics_enabled is True
        assert obj.show_views_on_posts is None

    def test_with_both_fields_succeeds(self) -> None:
        obj = AnalyticsSettingsUpdate(analytics_enabled=True, show_views_on_posts=False)
        assert obj.analytics_enabled is True
        assert obj.show_views_on_posts is False


class TestPathHitSchemaValidation:
    """Issue 7 + Suggestion 6: PathHit field constraints."""

    def test_path_id_zero_raises_validation_error(self) -> None:
        """path_id=0 is meaningless and should be rejected."""
        with pytest.raises(ValidationError):
            PathHit(path_id=0, path="/test", views=1)

    def test_path_id_negative_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PathHit(path_id=-1, path="/test", views=1)

    def test_path_id_one_succeeds(self) -> None:
        hit = PathHit(path_id=1, path="/test", views=1)
        assert hit.path_id == 1

    def test_empty_path_raises_validation_error(self) -> None:
        """Empty path string should be rejected."""
        with pytest.raises(ValidationError):
            PathHit(path_id=1, path="", views=1)


class TestPathReferrersResponseSchemaValidation:
    """PathReferrersResponse.path_id must enforce ge=1 like PathHit.path_id."""

    def test_path_referrers_response_rejects_zero_path_id(self) -> None:
        with pytest.raises(ValidationError):
            PathReferrersResponse(path_id=0, referrers=[])

    def test_path_referrers_response_rejects_negative_path_id(self) -> None:
        with pytest.raises(ValidationError):
            PathReferrersResponse(path_id=-1, referrers=[])

    def test_path_referrers_response_accepts_valid_path_id(self) -> None:
        resp = PathReferrersResponse(path_id=1, referrers=[])
        assert resp.path_id == 1


class TestPathReferrersEndpointValidation:
    """Referrers endpoint must validate path_id >= 1."""

    @pytest.mark.asyncio
    async def test_referrers_rejects_zero_path_id(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits/0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_referrers_rejects_negative_path_id(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/hits/-1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestPublicViewCountPathSanitization:
    """Issue 2: Input sanitization for public /views/{file_path:path} endpoint.

    These tests enable show_views_on_posts and mock GoatCounter so that valid
    paths reach the service call while invalid paths are rejected early by the
    sanitization check (returning views=None without hitting GoatCounter).
    """

    async def _enable_views(self, client: AsyncClient) -> None:
        """Enable show_views_on_posts so valid paths reach GoatCounter."""
        token = await _get_admin_token(client)
        await _enable_post_views(client, {"Authorization": f"Bearer {token}"})

    async def _create_post(self, client: AsyncClient, *, title: str) -> tuple[str, str]:
        """Create a published post and return (file_path, slug)."""
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        return await _create_published_post(client, headers, title=title)

    @pytest.mark.asyncio
    async def test_normal_path_reaches_service(self, client: AsyncClient) -> None:
        """A safe path should be forwarded to GoatCounter."""
        await self._enable_views(client)
        _, slug = await self._create_post(client, title="Analytics safe path")
        mock_data: dict[str, list[dict[str, object]]] = {
            "hits": [{"path": f"/post/{slug}", "count": 5}]
        }
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{slug}")
        assert resp.status_code == 200
        assert resp.json()["views"] == 5
        mock_req.assert_called_once()

    @pytest.mark.asyncio
    async def test_path_with_slashes_reaches_service(self, client: AsyncClient) -> None:
        await self._enable_views(client)
        file_path, _ = await self._create_post(client, title="Analytics canonical path")
        mock_data: dict[str, list[dict[str, object]]] = {"hits": []}
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value=mock_data),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{file_path}")
        assert resp.status_code == 200
        assert resp.json()["views"] == 0
        mock_req.assert_called_once()

    @pytest.mark.asyncio
    async def test_very_long_path_rejected_before_service(self, client: AsyncClient) -> None:
        """Paths longer than 200 characters should be rejected without calling GoatCounter."""
        await self._enable_views(client)
        long_path = "a" * 201
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": []}),
        ) as mock_req:
            resp = await client.get(f"/api/analytics/views/{long_path}")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_unicode_path_rejected_before_service(self, client: AsyncClient) -> None:
        """Paths with unicode characters should be rejected."""
        await self._enable_views(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": []}),
        ) as mock_req:
            resp = await client.get("/api/analytics/views/post-\u00e9\u00e8\u00ea")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_special_characters_rejected_before_service(self, client: AsyncClient) -> None:
        """Paths with HTML/shell special characters should be rejected."""
        await self._enable_views(client)
        for char in ["<", ">", "&", ";", '"', "'"]:
            with patch(
                "backend.services.analytics_service._stats_request",
                new=AsyncMock(return_value={"hits": []}),
            ) as mock_req:
                resp = await client.get(f"/api/analytics/views/post{char}evil")
            assert resp.status_code == 200, f"Failed for char={char!r}"
            assert resp.json()["views"] is None, f"Expected views=None for char={char!r}"
            mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_path_rejected(self, client: AsyncClient) -> None:
        """Empty file_path should return views=None."""
        await self._enable_views(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new=AsyncMock(return_value={"hits": []}),
        ) as mock_req:
            resp = await client.get("/api/analytics/views/")
        # FastAPI may return 200 with empty path or 307 redirect;
        # if it gets to our handler, views should be None
        if resp.status_code == 200:
            assert resp.json()["views"] is None
            mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_posts_etc_passwd_rejected(self, client: AsyncClient) -> None:
        """posts/%2E%2E/etc/passwd must be rejected by the sanitizer, not the DB lookup.

        The `..` segments are percent-encoded so the HTTP client does not
        normalize the path before reaching the FastAPI handler.  We mock
        ``_resolve_public_post_slug`` to always return a slug so that if the
        sanitizer fails to block the request the service *would* be reached
        and the test would fail via ``mock_slug.assert_not_called()``.
        """
        await self._enable_views(client)
        with patch(
            "backend.api.analytics._resolve_public_post_slug",
            new=AsyncMock(return_value="some-slug"),
        ) as mock_slug:
            resp = await client.get("/api/analytics/views/posts/%2E%2E/etc/passwd")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_slug.assert_not_called()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_leading_dotdot_rejected(self, client: AsyncClient) -> None:
        """%2E%2E/secret must be rejected by the sanitizer before the DB is consulted."""
        await self._enable_views(client)
        with patch(
            "backend.api.analytics._resolve_public_post_slug",
            new=AsyncMock(return_value="some-slug"),
        ) as mock_slug:
            resp = await client.get("/api/analytics/views/%2E%2E/secret")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_slug.assert_not_called()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_deep_path_rejected(self, client: AsyncClient) -> None:
        """posts/%2E%2E/%2E%2E/etc/shadow must be rejected by the sanitizer."""
        await self._enable_views(client)
        with patch(
            "backend.api.analytics._resolve_public_post_slug",
            new=AsyncMock(return_value="some-slug"),
        ) as mock_slug:
            resp = await client.get("/api/analytics/views/posts/%2E%2E/%2E%2E/etc/shadow")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_slug.assert_not_called()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_middle_segment_rejected(self, client: AsyncClient) -> None:
        """foo/%2E%2E/bar must be rejected by the sanitizer before the DB is consulted."""
        await self._enable_views(client)
        with patch(
            "backend.api.analytics._resolve_public_post_slug",
            new=AsyncMock(return_value="some-slug"),
        ) as mock_slug:
            resp = await client.get("/api/analytics/views/foo/%2E%2E/bar")
        assert resp.status_code == 200
        assert resp.json()["views"] is None
        mock_slug.assert_not_called()


# ── Fixtures for _resolve_public_post_slug unit tests ──────────────────────────


@pytest.fixture
async def _cache_tables(db_engine: AsyncEngine) -> None:
    """Create cache tables (PostCache) for unit tests."""
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS posts_fts"))
        await conn.run_sync(CacheBase.metadata.drop_all)
        await conn.run_sync(CacheBase.metadata.create_all)


@pytest.fixture
async def post_session(db_session: AsyncSession, _cache_tables: None) -> AsyncSession:
    """AsyncSession with cache tables created."""
    return db_session


class TestResolvePublicPostSlug:
    """Issue 9: Direct unit tests for _resolve_public_post_slug branching logic."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self, post_session: AsyncSession) -> None:
        """Empty path → None without touching the DB."""
        result = await _resolve_public_post_slug(post_session, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_none(self, post_session: AsyncSession) -> None:
        """Whitespace-only path → None without touching the DB."""
        result = await _resolve_public_post_slug(post_session, "   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_published_post_bare_slug_resolves(self, post_session: AsyncSession) -> None:
        """A bare slug for a published post resolves to that slug."""
        from datetime import UTC, datetime

        post_session.add(
            PostCache(
                file_path="posts/hello-world/index.md",
                title="Hello World",
                is_draft=False,
                created_at=datetime.now(UTC),
                modified_at=datetime.now(UTC),
                content_hash="abc123",
            )
        )
        await post_session.commit()

        result = await _resolve_public_post_slug(post_session, "hello-world")
        assert result == "hello-world"

    @pytest.mark.asyncio
    async def test_published_post_canonical_path_resolves(self, post_session: AsyncSession) -> None:
        """The canonical directory-backed path for a published post resolves to its slug."""
        from datetime import UTC, datetime

        post_session.add(
            PostCache(
                file_path="posts/canonical-post/index.md",
                title="Canonical Post",
                is_draft=False,
                created_at=datetime.now(UTC),
                modified_at=datetime.now(UTC),
                content_hash="def456",
            )
        )
        await post_session.commit()

        result = await _resolve_public_post_slug(post_session, "posts/canonical-post/index.md")
        assert result == "canonical-post"

    @pytest.mark.asyncio
    async def test_draft_post_returns_none(self, post_session: AsyncSession) -> None:
        """Draft posts must not be resolvable (non-enumerating)."""
        from datetime import UTC, datetime

        post_session.add(
            PostCache(
                file_path="posts/draft-post/index.md",
                title="Draft Post",
                is_draft=True,
                created_at=datetime.now(UTC),
                modified_at=datetime.now(UTC),
                content_hash="ghi789",
            )
        )
        await post_session.commit()

        result = await _resolve_public_post_slug(post_session, "draft-post")
        assert result is None

    @pytest.mark.asyncio
    async def test_nonexistent_post_returns_none(self, post_session: AsyncSession) -> None:
        """A slug that does not exist in the DB returns None."""
        result = await _resolve_public_post_slug(post_session, "does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_posts_prefix_non_canonical_returns_none(
        self, post_session: AsyncSession
    ) -> None:
        """A path starting with posts/ but not matching the canonical form is rejected."""
        # posts/flat.md is NOT a canonical directory-backed path
        result = await _resolve_public_post_slug(post_session, "posts/flat.md")
        assert result is None


class TestDashboardEndpoint:
    """Tests for the consolidated GET /dashboard endpoint."""

    @pytest.mark.asyncio
    async def test_dashboard_unauthenticated(self, client: AsyncClient) -> None:
        """Dashboard endpoint requires authentication."""
        resp = await client.get("/api/admin/analytics/dashboard")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard_503_when_analytics_disabled(self, client: AsyncClient) -> None:
        """Dashboard returns 503 when analytics are disabled."""
        token = await _get_admin_token(client)
        with patch(
            "backend.api.analytics.fetch_dashboard",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/admin/analytics/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_dashboard_happy_path(self, client: AsyncClient) -> None:
        """Dashboard endpoint returns all fields when GoatCounter succeeds."""
        from backend.schemas.analytics import (
            BreakdownResponse,
            DashboardResponse,
            PathHitsResponse,
            SiteReferrersResponse,
            TotalStatsResponse,
            ViewsOverTimeResponse,
        )

        token = await _get_admin_token(client)
        fake_dashboard = DashboardResponse(
            stats=TotalStatsResponse(visitors=200),
            paths=PathHitsResponse(paths=[]),
            views_over_time=ViewsOverTimeResponse(days=[]),
            browsers=BreakdownResponse(category="browsers", entries=[]),
            operating_systems=BreakdownResponse(category="systems", entries=[]),
            languages=BreakdownResponse(category="languages", entries=[]),
            locations=BreakdownResponse(category="locations", entries=[]),
            sizes=BreakdownResponse(category="sizes", entries=[]),
            campaigns=BreakdownResponse(category="campaigns", entries=[]),
            referrers=SiteReferrersResponse(referrers=[]),
        )

        with patch(
            "backend.api.analytics.fetch_dashboard",
            new=AsyncMock(return_value=fake_dashboard),
        ):
            resp = await client.get(
                "/api/admin/analytics/dashboard",
                params={"start": "2026-04-01T00:00:00Z", "end": "2026-04-30T23:59:59Z"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["visitors"] == 200
        assert "paths" in data
        assert "views_over_time" in data
        assert "browsers" in data
        assert "operating_systems" in data
        assert "languages" in data
        assert "locations" in data
        assert "sizes" in data
        assert "campaigns" in data
        assert "referrers" in data

    @pytest.mark.asyncio
    async def test_dashboard_rejects_invalid_date_param(self, client: AsyncClient) -> None:
        """Dashboard endpoint rejects unparseable date parameters."""
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/dashboard",
            params={"start": "not-a-date"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
