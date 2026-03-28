"""Profile update and username validation integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.config import Settings
from tests.conftest import create_test_client, create_test_user

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")

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


async def _login_admin(client: AsyncClient) -> dict[str, str]:
    """Login as admin and return headers with CSRF token."""
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


class TestProfileUpdate:
    async def test_update_display_name(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"display_name": "Admin User"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Admin User"
        assert data["username"] == "admin"

    async def test_update_username(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"username": "newadmin"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "newadmin"

    async def test_update_username_rejects_invalid_format(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"username": "bad user"},
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_update_username_rejects_duplicate(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        await create_test_user(client, "other", "other@test.com", "password123")
        resp = await client.patch(
            "/api/auth/me",
            json={"username": "other"},
            headers=headers,
        )
        assert resp.status_code == 409

    async def test_update_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/auth/me",
            json={"display_name": "Hacker"},
        )
        assert resp.status_code == 401

    async def test_clear_display_name(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        await client.patch(
            "/api/auth/me",
            json={"display_name": "Admin User"},
            headers=headers,
        )
        resp = await client.patch(
            "/api/auth/me",
            json={"display_name": ""},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] is None

    async def test_noop_update_succeeds(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200


class TestUsernameChangeUpdatesFiles:
    async def test_username_change_updates_post_author_on_disk(
        self, client: AsyncClient, tmp_content_dir: Path
    ) -> None:
        posts_dir = tmp_content_dir / "posts" / "2026-01-01-test"
        posts_dir.mkdir(parents=True, exist_ok=True)
        (posts_dir / "index.md").write_text(
            "---\ntitle: Test Post\nauthor: admin\n"
            "created_at: 2026-01-01\nmodified_at: 2026-01-01\n---\nHello\n"
        )

        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"username": "newadmin"},
            headers=headers,
        )
        assert resp.status_code == 200

        content = (posts_dir / "index.md").read_text()
        assert "author: newadmin" in content
        assert "author: admin" not in content

    async def test_username_change_does_not_affect_other_authors(
        self, client: AsyncClient, tmp_content_dir: Path
    ) -> None:
        posts_dir = tmp_content_dir / "posts" / "2026-01-02-other"
        posts_dir.mkdir(parents=True, exist_ok=True)
        (posts_dir / "index.md").write_text(
            "---\ntitle: Other Post\nauthor: someone_else\n"
            "created_at: 2026-01-02\nmodified_at: 2026-01-02\n---\nContent\n"
        )

        headers = await _login_admin(client)
        await client.patch(
            "/api/auth/me",
            json={"username": "newadmin"},
            headers=headers,
        )

        content = (posts_dir / "index.md").read_text()
        assert "author: someone_else" in content


class TestProfileUpdateEdgeCases:
    async def test_update_username_and_display_name_simultaneously(
        self, client: AsyncClient
    ) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"username": "newadmin", "display_name": "New Admin"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "newadmin"
        assert data["display_name"] == "New Admin"

    async def test_whitespace_only_display_name_normalized_to_null(
        self, client: AsyncClient
    ) -> None:
        headers = await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"display_name": "   "},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] is None

    async def test_patch_me_requires_csrf_token(self, client: AsyncClient) -> None:
        await _login_admin(client)
        resp = await client.patch(
            "/api/auth/me",
            json={"display_name": "Hacker"},
        )
        assert resp.status_code == 403

    async def test_get_me_reflects_username_change(self, client: AsyncClient) -> None:
        headers = await _login_admin(client)
        await client.patch(
            "/api/auth/me",
            json={"username": "newadmin"},
            headers=headers,
        )
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == "newadmin"


async def _login(client: AsyncClient) -> str:
    """Login as admin via token-login and return a Bearer token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestProfileUpdateAtomicity:
    """Username change must be atomic: if cache rebuild fails, filesystem must be reverted."""

    async def test_filesystem_reverted_on_rebuild_cache_failure(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)

        # Create a post first
        resp = await client.post(
            "/api/posts",
            json={"title": "Atomic Test", "body": "Content"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        # Now try to change username — but make rebuild_cache fail
        with patch(
            "backend.services.cache_service.rebuild_cache",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cache boom"),
        ):
            resp = await client.patch(
                "/api/auth/me",
                json={"username": "newname"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Should fail (500)
        assert resp.status_code == 500

        # Filesystem must still have the OLD author (admin), not the new one
        post_path = app_settings.content_dir / file_path
        content = post_path.read_text()
        assert "author: admin" in content
        assert "author: newname" not in content

    async def test_username_reverted_when_author_rewrite_fails(self, client: AsyncClient) -> None:
        """A post-author rewrite failure must revert the already-committed username change."""
        token = await _login(client)

        with patch(
            "backend.api.auth.update_author_in_posts",
            side_effect=OSError("disk full"),
        ):
            resp = await client.patch(
                "/api/auth/me",
                json={"username": "newname"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 500

        me_resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "admin"
