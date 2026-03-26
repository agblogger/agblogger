"""Tests for input validation improvements.

Covers: RequestValidationError format, sort/order/label_mode/date validation,
ValueError forwarding, page ID error message, crosspost schema limits.
"""

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
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
    )
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
    )
    (tmp_content_dir / "about.md").write_text("# About\n\nAbout page.\n")

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


async def login(client: AsyncClient) -> str:
    """Login as admin and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestRequestValidationErrorFormat:
    """Custom RequestValidationError handler returns structured detail."""

    @pytest.mark.asyncio
    async def test_422_returns_field_and_message(self, client: AsyncClient) -> None:
        """422 responses should contain {field, message} items."""
        token = await login(client)
        # Send invalid data: title is required but sending empty string triggers min_length
        resp = await client.post(
            "/api/posts",
            json={"title": "", "body": "content", "labels": [], "is_draft": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        detail = data["detail"]
        assert isinstance(detail, list)
        assert len(detail) > 0
        item = detail[0]
        assert "field" in item
        assert "message" in item

    @pytest.mark.asyncio
    async def test_422_field_name_is_human_readable(self, client: AsyncClient) -> None:
        """Field name should be the last component of the location path."""
        token = await login(client)
        resp = await client.post(
            "/api/posts",
            json={"body": "content", "labels": [], "is_draft": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        fields = [item["field"] for item in detail]
        assert "title" in fields


class TestSortOrderLabelModeValidation:
    """Sort, order, and label_mode params reject invalid values with 422."""

    @pytest.mark.asyncio
    async def test_invalid_sort_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?sort=invalid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_order_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?order=invalid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_label_mode_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?labelMode=invalid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_sort_values_work(self, client: AsyncClient) -> None:
        for sort_val in ("created_at", "modified_at", "title", "author"):
            resp = await client.get(f"/api/posts?sort={sort_val}")
            assert resp.status_code == 200, f"sort={sort_val} should be valid"

    @pytest.mark.asyncio
    async def test_valid_order_values_work(self, client: AsyncClient) -> None:
        for order_val in ("asc", "desc"):
            resp = await client.get(f"/api/posts?order={order_val}")
            assert resp.status_code == 200, f"order={order_val} should be valid"

    @pytest.mark.asyncio
    async def test_valid_label_mode_values_work(self, client: AsyncClient) -> None:
        for mode in ("and", "or"):
            resp = await client.get(f"/api/posts?labelMode={mode}")
            assert resp.status_code == 200, f"labelMode={mode} should be valid"


class TestPaginationValidation:
    """Pagination params reject values that would overflow SQLite offsets."""

    @pytest.mark.asyncio
    async def test_posts_page_too_large_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/posts",
            params={"page": "78023892654793026803456065670889502677827644", "per_page": 10},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert any(item["field"] == "page" for item in detail)

    @pytest.mark.asyncio
    async def test_label_posts_page_too_large_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/labels/swe/posts",
            params={"page": "78023892654793026803456065670889502677827644", "per_page": 10},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert any(item["field"] == "page" for item in detail)


class TestDateFilterValidation:
    """Invalid date filters return 400 with descriptive message."""

    @pytest.mark.asyncio
    async def test_invalid_from_date_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?from=not-a-date")
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invalid_to_date_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?to=not-a-date")
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_valid_dates_still_work(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?from=2026-01-01&to=2026-12-31")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_iso_timestamps_work(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/posts?from=2026-01-01T00:00:00.000Z&to=2026-12-31T23:59:59.999Z"
        )
        assert resp.status_code == 200


class TestValueErrorForwarding:
    """ValueError handler returns a generic message to avoid leaking internals."""

    @pytest.mark.asyncio
    async def test_value_error_returns_generic_detail(self, client: AsyncClient) -> None:
        """The ValueError handler should return a generic message, not the exception text."""
        from unittest.mock import AsyncMock, patch

        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=ValueError("Custom validation message from service"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid value"


class TestPageIdErrorMessage:
    """Page ID validation error explains the required format."""

    @pytest.mark.asyncio
    async def test_invalid_page_id_put_explains_format(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.put(
            "/api/admin/pages/INVALID!",
            json={"title": "Test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        # Should explain the allowed format, not just say "Invalid page ID"
        assert "lowercase" in detail or "a-z" in detail or "alphanumeric" in detail

    @pytest.mark.asyncio
    async def test_invalid_page_id_delete_explains_format(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.delete(
            "/api/admin/pages/INVALID!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "lowercase" in detail or "a-z" in detail or "alphanumeric" in detail


class TestTimezoneValidation:
    """Admin site settings reject invalid timezone strings."""

    @pytest.mark.asyncio
    async def test_invalid_timezone_rejected(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.put(
            "/api/admin/site",
            json={"title": "Blog", "timezone": "Not/A/Timezone"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_timezone_rejected(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.put(
            "/api/admin/site",
            json={"title": "Blog", "timezone": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_timezone_accepted(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.put(
            "/api/admin/site",
            json={"title": "Blog", "timezone": "America/New_York"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestCrosspostSchemaLimits:
    """Crosspost schemas enforce max_length constraints."""

    def test_platform_max_length_rejected(self) -> None:
        """Platform name over 50 chars should be rejected."""
        from pydantic import ValidationError

        from backend.schemas.crosspost import SocialAccountCreate

        with pytest.raises(ValidationError):
            SocialAccountCreate(
                platform="x" * 51,
                account_name="test",
                credentials={"key": "val"},
            )

    def test_platform_valid_length_accepted(self) -> None:
        from backend.schemas.crosspost import SocialAccountCreate

        account = SocialAccountCreate(
            platform="bluesky",
            account_name="test",
            credentials={"key": "val"},
        )
        assert account.platform == "bluesky"

    def test_post_path_max_length_rejected(self) -> None:
        """post_path over 500 chars should be rejected."""
        from pydantic import ValidationError

        from backend.schemas.crosspost import CrossPostRequest

        with pytest.raises(ValidationError):
            CrossPostRequest(
                post_path="x" * 501,
                platforms=["bluesky"],
            )

    def test_post_path_valid_length_accepted(self) -> None:
        from backend.schemas.crosspost import CrossPostRequest

        req = CrossPostRequest(
            post_path="posts/2026-01-01-test/index.md",
            platforms=["bluesky"],
        )
        assert req.post_path == "posts/2026-01-01-test/index.md"
