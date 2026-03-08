"""Tests for admin display name update endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from backend.schemas.admin import DisplayNameUpdate
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

    from backend.filesystem.frontmatter import PostData


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

        settings_resp = await client.get("/api/admin/site", headers=headers)
        assert settings_resp.status_code == 200
        assert settings_resp.json()["default_author"] == "Updated Author"

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

    @pytest.mark.asyncio
    async def test_returns_error_and_rolls_back_when_post_rewrite_fails(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Rollback Post",
                "body": "Hello world",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]
        post_file = app_settings.content_dir / file_path
        original_content = post_file.read_text(encoding="utf-8")

        from backend.filesystem.content_manager import ContentManager

        original_write_post = ContentManager.write_post

        def failing_write_post(self: ContentManager, rel_path: str, post_data: PostData) -> None:
            if rel_path == file_path:
                raise OSError("disk full")
            original_write_post(self, rel_path, post_data)

        with patch.object(ContentManager, "write_post", new=failing_write_post):
            resp = await client.put(
                "/api/admin/display-name",
                json={"display_name": "Updated Author"},
                headers=headers,
            )

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert file_path in detail

        me_resp = await client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["display_name"] == "Admin"

        post_resp = await client.get(f"/api/posts/{file_path}", headers=headers)
        assert post_resp.status_code == 200
        assert post_resp.json()["author"] == "Admin"

        assert post_file.read_text(encoding="utf-8") == original_content

    @pytest.mark.asyncio
    async def test_partial_file_failure_rolls_back_all_changes(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """When one of multiple post files fails to update, all changes roll back."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create two posts
        resp1 = await client.post(
            "/api/posts",
            json={"title": "Post One", "body": "Content one", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert resp1.status_code == 201
        file_path1 = resp1.json()["file_path"]

        resp2 = await client.post(
            "/api/posts",
            json={"title": "Post Two", "body": "Content two", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert resp2.status_code == 201
        file_path2 = resp2.json()["file_path"]

        post_file1 = app_settings.content_dir / file_path1
        post_file2 = app_settings.content_dir / file_path2
        original1 = post_file1.read_text(encoding="utf-8")
        original2 = post_file2.read_text(encoding="utf-8")

        from backend.filesystem.content_manager import ContentManager

        original_write_post = ContentManager.write_post

        def failing_write_post(self: ContentManager, rel_path: str, post_data: PostData) -> None:
            # Only the second post fails
            if rel_path == file_path2:
                raise OSError("permission denied")
            original_write_post(self, rel_path, post_data)

        with patch.object(ContentManager, "write_post", new=failing_write_post):
            resp = await client.put(
                "/api/admin/display-name",
                json={"display_name": "New Name"},
                headers=headers,
            )

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        # The response should identify which file(s) failed
        assert file_path2 in detail

        # DB should be rolled back - user display name unchanged
        me_resp = await client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["display_name"] == "Admin"

        # Both posts should have original author in DB cache
        post1_resp = await client.get(f"/api/posts/{file_path1}", headers=headers)
        assert post1_resp.status_code == 200
        assert post1_resp.json()["author"] == "Admin"

        post2_resp = await client.get(f"/api/posts/{file_path2}", headers=headers)
        assert post2_resp.status_code == 200
        assert post2_resp.json()["author"] == "Admin"

        # Disk files should be unchanged
        assert post_file1.read_text(encoding="utf-8") == original1
        assert post_file2.read_text(encoding="utf-8") == original2

    @pytest.mark.asyncio
    async def test_db_commit_failure_rolls_back_files_and_site_config(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Commit Rollback Post",
                "body": "Hello world",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        post_file = app_settings.content_dir / file_path
        original_post_content = post_file.read_text(encoding="utf-8")
        original_index_toml = (app_settings.content_dir / "index.toml").read_text(encoding="utf-8")

        with patch(
            "sqlalchemy.ext.asyncio.AsyncSession.commit",
            side_effect=OperationalError("database locked", {}, Exception()),
        ):
            resp = await client.put(
                "/api/admin/display-name",
                json={"display_name": "Updated Author"},
                headers=headers,
            )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Database temporarily unavailable"

        me_resp = await client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["display_name"] == "Admin"

        post_resp = await client.get(f"/api/posts/{file_path}", headers=headers)
        assert post_resp.status_code == 200
        assert post_resp.json()["author"] == "Admin"

        assert post_file.read_text(encoding="utf-8") == original_post_content
        current_index_toml = (app_settings.content_dir / "index.toml").read_text(encoding="utf-8")
        assert current_index_toml == original_index_toml


class TestDisplayNameUpdateSchema:
    """Tests for DisplayNameUpdate schema validation."""

    def test_strips_leading_whitespace(self) -> None:
        schema = DisplayNameUpdate(display_name="  Alice")
        assert schema.display_name == "Alice"

    def test_strips_trailing_whitespace(self) -> None:
        schema = DisplayNameUpdate(display_name="Alice  ")
        assert schema.display_name == "Alice"

    def test_strips_surrounding_whitespace(self) -> None:
        schema = DisplayNameUpdate(display_name="  Alice  ")
        assert schema.display_name == "Alice"

    def test_whitespace_only_becomes_empty(self) -> None:
        schema = DisplayNameUpdate(display_name="   ")
        assert schema.display_name == ""

    def test_no_whitespace_unchanged(self) -> None:
        schema = DisplayNameUpdate(display_name="Alice")
        assert schema.display_name == "Alice"
