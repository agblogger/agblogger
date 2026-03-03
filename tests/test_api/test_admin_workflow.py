"""Admin page management workflow integration tests."""

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
    """Create settings for admin workflow tests."""
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


async def _login(client: AsyncClient) -> str:
    """Login as admin and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestAdminPageWorkflow:
    """Admin page management lifecycle: create -> update -> reorder -> delete."""

    @pytest.mark.asyncio
    async def test_full_page_lifecycle(self, client: AsyncClient) -> None:
        # Step 1: Login as admin
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: Create a new page
        create_resp = await client.post(
            "/api/admin/pages",
            json={"id": "about", "title": "About"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["id"] == "about"
        assert created["title"] == "About"

        # Step 3: Update the page content
        update_resp = await client.put(
            "/api/admin/pages/about",
            json={"title": "About Us", "content": "# About Us\n\nWe are a team of writers."},
            headers=headers,
        )
        assert update_resp.status_code == 200

        # Step 4: Create a second page
        create2_resp = await client.post(
            "/api/admin/pages",
            json={"id": "contact", "title": "Contact"},
            headers=headers,
        )
        assert create2_resp.status_code == 201
        assert create2_resp.json()["id"] == "contact"

        # Step 5: Verify both pages exist
        pages_resp = await client.get("/api/admin/pages", headers=headers)
        assert pages_resp.status_code == 200
        pages_data = pages_resp.json()
        page_ids = [p["id"] for p in pages_data["pages"]]
        assert "about" in page_ids
        assert "contact" in page_ids

        # Step 6: Reorder pages - put contact before about
        # Build the reorder payload using the current page data
        pages_list = pages_data["pages"]
        reorder_pages = [
            {"id": p["id"], "title": p["title"], "file": p.get("file")} for p in pages_list
        ]
        # Move "contact" before "about" by rearranging the list
        contact_page = next(p for p in reorder_pages if p["id"] == "contact")
        about_page = next(p for p in reorder_pages if p["id"] == "about")
        # Keep timeline and any other builtin pages, put contact first among custom pages
        new_order = [p for p in reorder_pages if p["id"] not in ("about", "contact")]
        new_order.extend([contact_page, about_page])

        reorder_resp = await client.put(
            "/api/admin/pages/order",
            json={"pages": new_order},
            headers=headers,
        )
        assert reorder_resp.status_code == 200

        # Step 7: Verify order persisted
        verify_resp = await client.get("/api/admin/pages", headers=headers)
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        verify_ids = [p["id"] for p in verify_data["pages"]]
        # Contact should appear before about in the list
        assert verify_ids.index("contact") < verify_ids.index("about")

        # Step 8: Delete the second page
        delete_resp = await client.delete(
            "/api/admin/pages/contact",
            headers=headers,
        )
        assert delete_resp.status_code == 204

        # Step 9: Verify only first page remains (among custom pages)
        final_resp = await client.get("/api/admin/pages", headers=headers)
        assert final_resp.status_code == 200
        final_data = final_resp.json()
        final_ids = [p["id"] for p in final_data["pages"]]
        assert "about" in final_ids
        assert "contact" not in final_ids

    @pytest.mark.asyncio
    async def test_page_endpoints_require_auth(self, client: AsyncClient) -> None:
        """All admin page endpoints should require authentication."""
        # GET pages list
        resp = await client.get("/api/admin/pages")
        assert resp.status_code == 401

        # POST create page
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "test", "title": "Test"},
        )
        assert resp.status_code == 401

        # PUT update page
        resp = await client.put(
            "/api/admin/pages/test",
            json={"title": "Updated"},
        )
        assert resp.status_code == 401

        # DELETE page
        resp = await client.delete("/api/admin/pages/test")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_duplicate_page_id_returns_409(self, client: AsyncClient) -> None:
        """Creating a page with an existing ID should return 409."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create first page
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "duplicate", "title": "First"},
            headers=headers,
        )
        assert resp.status_code == 201

        # Try to create with same ID
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "duplicate", "title": "Second"},
            headers=headers,
        )
        assert resp.status_code == 409
