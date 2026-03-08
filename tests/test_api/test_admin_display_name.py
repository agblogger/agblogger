"""Tests for admin display name update endpoint."""

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


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestUpdateDisplayName:
    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": "New Name"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_updates_display_name(self, client: AsyncClient) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": "New Display Name"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "New Display Name"

        # Verify via /me endpoint
        me_resp = await client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["display_name"] == "New Display Name"

    @pytest.mark.asyncio
    async def test_empty_display_name_sets_null(self, client: AsyncClient) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": ""},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] is None

    @pytest.mark.asyncio
    async def test_display_name_too_long(self, client: AsyncClient) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": "x" * 101},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_retroactively_updates_posts(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post (author will be set from user's display_name/username)
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Test Post",
                "body": "Hello world",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        post = create_resp.json()
        file_path = post["file_path"]

        # Change display name
        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": "Updated Author"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Check post was updated in API
        post_resp = await client.get(f"/api/posts/{file_path}", headers=headers)
        assert post_resp.status_code == 200
        assert post_resp.json()["author"] == "Updated Author"

        # Check markdown file on disk was updated
        post_file = app_settings.content_dir / file_path
        content = post_file.read_text(encoding="utf-8")
        assert "author: Updated Author" in content

    @pytest.mark.asyncio
    async def test_does_not_update_other_users_posts(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post file with a different author_username
        posts_dir = app_settings.content_dir / "posts"
        other_post_dir = posts_dir / "2026-01-01-other-post"
        other_post_dir.mkdir(parents=True)
        (other_post_dir / "index.md").write_text(
            "---\n"
            "title: Other Post\n"
            "created_at: 2026-01-01 00:00:00+00:00\n"
            "modified_at: 2026-01-01 00:00:00+00:00\n"
            "author: Other Author\n"
            "author_username: otheruser\n"
            "---\n\nOther content\n",
            encoding="utf-8",
        )

        # Rebuild cache to pick up the manually created post
        resp = await client.put(
            "/api/admin/display-name",
            json={"display_name": "Admin New Name"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify other user's post was NOT updated on disk
        other_content = (other_post_dir / "index.md").read_text(encoding="utf-8")
        assert "author: Other Author" in other_content
