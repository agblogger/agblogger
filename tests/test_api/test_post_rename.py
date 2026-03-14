"""Tests for directory rename with symlink on post title change."""

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
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    """Login and return the access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


async def _create_post(client: AsyncClient, token: str, title: str) -> dict[str, str]:
    """Create a post and return the response data."""
    resp = await client.post(
        "/api/posts",
        json={
            "title": title,
            "body": "Some content here.\n",
            "labels": [],
            "is_draft": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


class TestPostRename:
    @pytest.mark.asyncio
    async def test_rename_changes_directory(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """When the title changes, update_post should rename the directory and return new path."""
        token = await _login(client)
        data = await _create_post(client, token, "Original Title")
        original_path = data["file_path"]
        assert "original-title" in original_path
        assert original_path.endswith("/index.md")

        # Update with a different title
        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Brand New Title",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]
        assert "brand-new-title" in new_path
        assert new_path != original_path
        assert new_path.endswith("/index.md")

        # Verify the new file exists on disk
        new_full = app_settings.content_dir / new_path
        assert new_full.exists()

    @pytest.mark.asyncio
    async def test_rename_creates_symlink(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """After rename, the old directory path should be a symlink to the new one."""
        token = await _login(client)
        data = await _create_post(client, token, "Symlink Source")
        original_path = data["file_path"]

        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Symlink Target",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]

        # Old directory should be a symlink
        old_dir = app_settings.content_dir / original_path
        old_dir = old_dir.parent  # directory, not index.md
        assert old_dir.is_symlink()

        # The symlink should resolve to the new directory
        new_dir = app_settings.content_dir / new_path
        new_dir = new_dir.parent
        assert old_dir.resolve() == new_dir.resolve()

    @pytest.mark.asyncio
    async def test_rename_preserves_assets(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Assets in the post directory should survive a rename."""
        token = await _login(client)
        data = await _create_post(client, token, "Asset Post")
        original_path = data["file_path"]
        headers = {"Authorization": f"Bearer {token}"}

        # Upload an asset
        import io

        asset_content = b"fake image data"
        resp = await client.post(
            f"/api/posts/{original_path}/assets",
            files={"files": ("photo.png", io.BytesIO(asset_content), "image/png")},
            headers=headers,
        )
        assert resp.status_code == 200

        # Rename the post
        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Renamed Asset Post",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]

        # Asset should exist in the new directory
        new_dir = app_settings.content_dir / new_path
        new_asset = new_dir.parent / "photo.png"
        assert new_asset.exists()
        assert new_asset.read_bytes() == asset_content

    @pytest.mark.asyncio
    async def test_no_rename_when_slug_unchanged(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """If the slug doesn't change, the directory should stay the same."""
        token = await _login(client)
        data = await _create_post(client, token, "Stable Title")
        original_path = data["file_path"]

        # Update with the same title (slug doesn't change)
        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Stable Title",
                "body": "Updated content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["file_path"] == original_path

        # No symlink created
        old_dir = app_settings.content_dir / original_path
        assert not old_dir.parent.is_symlink()

    @pytest.mark.asyncio
    async def test_old_url_works_via_symlink(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Content at the old path should still be accessible via the symlink."""
        token = await _login(client)
        data = await _create_post(client, token, "Readable Original")
        original_path = data["file_path"]

        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Readable Renamed",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]
        assert new_path != original_path

        # The old file path should still be readable on disk through the symlink
        old_full = app_settings.content_dir / original_path
        assert old_full.exists()
        content = old_full.read_text(encoding="utf-8")
        assert "Readable Renamed" in content

    @pytest.mark.asyncio
    async def test_old_url_accessible_unauthenticated_for_published_post(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Published post content should be accessible via old symlink path without auth."""
        token = await _login(client)
        data = await _create_post(client, token, "Public Original")
        original_path = data["file_path"]

        # Rename the post
        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Public Renamed",
                "body": "Accessible content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]
        assert new_path != original_path

        # Access the old path via the content API without authentication
        resp = await client.get(f"/api/content/{original_path}")
        assert resp.status_code == 200
        assert "Accessible content." in resp.text

    @pytest.mark.asyncio
    async def test_no_rename_for_flat_file_posts(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Flat file posts (not ending in /index.md) should not be renamed."""
        # Create a flat file post directly on disk
        posts_dir = app_settings.content_dir / "posts"
        flat_post = posts_dir / "flat-post.md"
        flat_post.write_text(
            "---\ntitle: Flat Post\ncreated_at: 2026-02-02 22:21:29+00\n"
            "author: admin\nlabels: []\n---\nContent.\n"
        )

        # Rebuild cache so the post is indexed
        from backend.database import create_engine
        from backend.filesystem.content_manager import ContentManager
        from backend.services.cache_service import rebuild_cache

        engine, session_factory = create_engine(app_settings)
        cm = ContentManager(content_dir=app_settings.content_dir)
        await rebuild_cache(session_factory, cm)
        await engine.dispose()

        token = await _login(client)

        # Update the flat post with a new title - it should NOT rename
        resp = await client.put(
            "/api/posts/posts/flat-post.md",
            json={
                "title": "Renamed Flat Post",
                "body": "Content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # File path should remain unchanged for flat files
        assert resp.json()["file_path"] == "posts/flat-post.md"

    @pytest.mark.asyncio
    async def test_rename_collision_appends_suffix(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """If the target directory already exists, append -2, -3, etc."""
        token = await _login(client)

        # Create two posts that will both want the same slug after rename
        data1 = await _create_post(client, token, "Collision Alpha")
        data2 = await _create_post(client, token, "Collision Beta")

        path1 = data1["file_path"]
        path2 = data2["file_path"]

        # Rename the first post to "Collision Target"
        resp1 = await client.put(
            f"/api/posts/{path1}",
            json={
                "title": "Collision Target",
                "body": "First post.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        new_path1 = resp1.json()["file_path"]
        assert "collision-target" in new_path1

        # Rename the second post to the same title
        resp2 = await client.put(
            f"/api/posts/{path2}",
            json={
                "title": "Collision Target",
                "body": "Second post.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        new_path2 = resp2.json()["file_path"]
        assert "collision-target" in new_path2
        # Should have a collision suffix
        assert new_path2 != new_path1
        # Both files should exist
        assert (app_settings.content_dir / new_path1).exists()
        assert (app_settings.content_dir / new_path2).exists()

    @pytest.mark.asyncio
    async def test_rename_collision_counter_increments(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """When multiple renames collide, suffixes should increment: -2, -3, etc."""
        token = await _login(client)

        data_a = await _create_post(client, token, "Alpha")
        data_b = await _create_post(client, token, "Beta")
        data_c = await _create_post(client, token, "Gamma")

        path_a = data_a["file_path"]
        path_b = data_b["file_path"]
        path_c = data_c["file_path"]

        # Rename B to "Alpha" -> directory should get a -2 suffix
        resp_b = await client.put(
            f"/api/posts/{path_b}",
            json={
                "title": "Alpha",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_b.status_code == 200
        new_path_b = resp_b.json()["file_path"]
        assert "-2" in new_path_b

        # Rename C to "Alpha" -> directory should get a -3 suffix
        resp_c = await client.put(
            f"/api/posts/{path_c}",
            json={
                "title": "Alpha",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_c.status_code == 200
        new_path_c = resp_c.json()["file_path"]
        assert "-3" in new_path_c

        # All three should have distinct paths
        all_paths = {path_a, new_path_b, new_path_c}
        assert len(all_paths) == 3

        # All three files should exist on disk
        assert (app_settings.content_dir / path_a).exists()
        assert (app_settings.content_dir / new_path_b).exists()
        assert (app_settings.content_dir / new_path_c).exists()

    @pytest.mark.asyncio
    async def test_old_api_path_redirects_to_new_path(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """GET /api/posts/{old_path} should 301 redirect to new path after rename."""
        token = await _login(client)
        data = await _create_post(client, token, "Redirect Source")
        original_path = data["file_path"]

        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Redirect Target",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_path = resp.json()["file_path"]
        assert new_path != original_path

        # GET the old path - should redirect
        resp = await client.get(
            f"/api/posts/{original_path}",
            follow_redirects=False,
        )
        assert resp.status_code == 301
        assert new_path in resp.headers["location"]

    @pytest.mark.asyncio
    async def test_old_api_path_redirect_serves_correct_post(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Following the redirect from old path should serve the renamed post."""
        token = await _login(client)
        data = await _create_post(client, token, "Follow Source")
        original_path = data["file_path"]

        resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Follow Target",
                "body": "Some content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # GET the old path with follow_redirects=True
        resp = await client.get(
            f"/api/posts/{original_path}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Follow Target"

    @pytest.mark.asyncio
    async def test_symlink_redirect_rejects_path_traversal(
        self, client: AsyncClient
    ) -> None:
        """GET /api/posts/ with .. segments should return 404, not probe the filesystem."""
        resp = await client.get("/api/posts/posts/../../etc/passwd")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_symlink_redirect_handles_broken_symlink(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """A broken symlink at a post path should return 404, not 500."""
        posts_dir = app_settings.content_dir / "posts"
        broken_dir = posts_dir / "broken-link"
        broken_dir.symlink_to("nonexistent-target")

        resp = await client.get("/api/posts/posts/broken-link/index.md")
        assert resp.status_code == 404
