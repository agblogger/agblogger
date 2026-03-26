"""Integration tests for analytics API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from backend.config import Settings
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
            "hits": [{"path": f"/post/{slug}", "count": 42, "count_unique": 30}]
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
            new=AsyncMock(
                return_value={"hits": [{"path": f"/post/{slug}", "count": 42, "count_unique": 30}]}
            ),
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
            new=AsyncMock(
                return_value={"hits": [{"path": f"/post/{slug}", "count": 42, "count_unique": 30}]}
            ),
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
            new=AsyncMock(return_value={"total": 1, "total_unique": 1}),
        ) as mock_req:
            resp = await client.get(
                "/api/admin/analytics/stats/total",
                headers=headers,
            )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Analytics service unavailable"
        mock_req.assert_not_called()


class TestDateParameterValidation:
    """Tests for date parameter regex validation."""

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
    async def test_total_stats_accepts_out_of_range_date_format(self, client: AsyncClient) -> None:
        """Regex only checks format, not calendar validity."""
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/total",
            params={"start": "2024-13-45"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Pattern matches — not 422
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
    async def test_breakdown_rejects_invalid_date(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers",
            params={"start": "2024/01/01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestSchemaValidation:
    """Tests for Pydantic ge=0 constraints on count fields."""

    def test_total_stats_rejects_negative_total_views(self) -> None:
        with pytest.raises(ValidationError):
            TotalStatsResponse(total_views=-1, total_unique=0)

    def test_total_stats_rejects_negative_total_unique(self) -> None:
        with pytest.raises(ValidationError):
            TotalStatsResponse(total_views=0, total_unique=-1)

    def test_total_stats_accepts_zero(self) -> None:
        resp = TotalStatsResponse(total_views=0, total_unique=0)
        assert resp.total_views == 0
        assert resp.total_unique == 0

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
            PathHit(path_id=0, path="/test", views=1, unique=1)

    def test_path_id_negative_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PathHit(path_id=-1, path="/test", views=1, unique=1)

    def test_path_id_one_succeeds(self) -> None:
        hit = PathHit(path_id=1, path="/test", views=1, unique=1)
        assert hit.path_id == 1

    def test_empty_path_raises_validation_error(self) -> None:
        """Empty path string should be rejected."""
        with pytest.raises(ValidationError):
            PathHit(path_id=1, path="", views=1, unique=1)


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
            "hits": [{"path": f"/post/{slug}", "count": 5, "count_unique": 3}]
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
