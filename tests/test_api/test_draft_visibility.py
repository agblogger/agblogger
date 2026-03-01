"""Tests for draft post visibility restrictions.

Draft posts should only be visible to their author. This includes:
- Post listings (GET /api/posts)
- Post detail (GET /api/posts/{path})
- Post edit (GET /api/posts/{path}/edit)
- Content file serving (GET /api/content/{path})
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
def draft_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for draft visibility tests."""
    # Add a published post by Admin
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "published.md").write_text(
        "---\ntitle: Published Post\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: Admin\nlabels: []\n---\nPublished content.\n"
    )
    # Add a draft post by Admin
    (posts_dir / "admin-draft.md").write_text(
        "---\ntitle: Admin Draft\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: Admin\nlabels: []\ndraft: true\n---\nDraft content.\n"
    )
    # Add a draft post directory with an image asset
    draft_dir = posts_dir / "draft-with-asset"
    draft_dir.mkdir()
    (draft_dir / "index.md").write_text(
        "---\ntitle: Draft With Asset\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: Admin\nlabels: []\ndraft: true\n---\nDraft with image.\n"
    )
    (draft_dir / "photo.png").write_bytes(b"fake-png-data")
    # Add a published post directory with an image asset
    pub_dir = posts_dir / "published-with-asset"
    pub_dir.mkdir()
    (pub_dir / "index.md").write_text(
        "---\ntitle: Published With Asset\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: Admin\nlabels: []\n---\nPublished with image.\n"
    )
    (pub_dir / "banner.png").write_bytes(b"fake-banner-png")

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
async def client(draft_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client."""
    async with create_test_client(draft_settings) as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> str:
    """Login and return access token."""
    resp = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_and_login(client: AsyncClient, username: str, email: str, password: str) -> str:
    """Register a new user and return access token."""
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 201
    return await _login(client, username, password)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestDraftListingVisibility:
    """Draft posts should only appear in listings for the author."""

    @pytest.mark.asyncio
    async def test_draft_not_in_public_listing(self, client: AsyncClient) -> None:
        """Unauthenticated users should not see draft posts in listings."""
        resp = await client.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles
        assert "Draft With Asset" not in titles

    @pytest.mark.asyncio
    async def test_draft_in_listing_for_author(self, client: AsyncClient) -> None:
        """The author should see their own drafts in listings."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" in titles
        assert "Draft With Asset" in titles

    @pytest.mark.asyncio
    async def test_draft_not_in_listing_for_other_user(self, client: AsyncClient) -> None:
        """A different authenticated user should not see another user's drafts."""
        token = await _register_and_login(client, "other", "other@test.com", "password1234")
        resp = await client.get("/api/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles
        assert "Draft With Asset" not in titles


class TestDraftDetailVisibility:
    """Draft post detail endpoint should restrict access to the author."""

    @pytest.mark.asyncio
    async def test_draft_get_returns_404_for_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated users get 404 for draft posts."""
        resp = await client.get("/api/posts/posts/admin-draft.md")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_get_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A different authenticated user gets 404 for another user's draft."""
        token = await _register_and_login(client, "other2", "other2@test.com", "password1234")
        resp = await client.get(
            "/api/posts/posts/admin-draft.md",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_get_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access their own draft."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/posts/posts/admin-draft.md",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Admin Draft"


class TestDraftEditVisibility:
    """Draft post edit endpoint should restrict access to the author."""

    @pytest.mark.asyncio
    async def test_draft_edit_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A non-admin authenticated user is forbidden from using draft edit endpoint."""
        token = await _register_and_login(client, "other3", "other3@test.com", "password1234")
        resp = await client.get(
            "/api/posts/posts/admin-draft.md/edit",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_draft_edit_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access their own draft for editing."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/posts/posts/admin-draft.md/edit",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Admin Draft"


class TestDraftContentFileVisibility:
    """Content file serving should restrict draft post assets to the author."""

    @pytest.mark.asyncio
    async def test_draft_asset_returns_404_for_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated users get 404 for draft post assets."""
        resp = await client.get("/api/content/posts/draft-with-asset/photo.png")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_asset_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A different authenticated user gets 404 for draft post assets."""
        token = await _register_and_login(client, "other4", "other4@test.com", "password1234")
        resp = await client.get(
            "/api/content/posts/draft-with-asset/photo.png",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_asset_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access assets in their draft post directories."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/content/posts/draft-with-asset/photo.png",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_published_asset_accessible_without_auth(self, client: AsyncClient) -> None:
        """Assets for published posts remain publicly accessible."""
        resp = await client.get("/api/content/posts/published-with-asset/banner.png")
        assert resp.status_code == 200
