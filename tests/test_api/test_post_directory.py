"""Tests for post-per-directory creation (server-side path generation)."""

from __future__ import annotations

import re
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
    # Add labels
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
    )
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


class TestPostDirectoryCreation:
    """Tests for creating posts without file_path (server generates the path)."""

    @pytest.mark.asyncio
    async def test_create_post_without_file_path(self, client: AsyncClient) -> None:
        """Creating a post without file_path should return 201 with a generated path."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "My First Post",
                "body": "Hello world content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # Path should be in posts/ directory and end with /index.md
        assert data["file_path"].startswith("posts/")
        assert data["file_path"].endswith("/index.md")
        # Path should contain a date-slug pattern
        assert re.search(r"\d{4}-\d{2}-\d{2}-my-first-post", data["file_path"])

    @pytest.mark.asyncio
    async def test_collision_handling_same_title(self, client: AsyncClient) -> None:
        """Two posts with the same title should get different paths."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp1 = await client.post(
            "/api/posts",
            json={
                "title": "Duplicate Title",
                "body": "First post.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/posts",
            json={
                "title": "Duplicate Title",
                "body": "Second post.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp2.status_code == 201

        path1 = resp1.json()["file_path"]
        path2 = resp2.json()["file_path"]
        assert path1 != path2
        # Both should be in posts/ and end with /index.md
        assert path1.endswith("/index.md")
        assert path2.endswith("/index.md")
        # Second should have a -2 suffix
        assert "-2/index.md" in path2

    @pytest.mark.asyncio
    async def test_created_post_accessible_via_get(self, client: AsyncClient) -> None:
        """A created post should be accessible via GET /api/posts/{file_path}."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Accessible Post",
                "body": "This should be readable.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        get_resp = await client.get(f"/api/posts/{file_path}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["title"] == "Accessible Post"
        assert data["file_path"] == file_path

    @pytest.mark.asyncio
    async def test_post_directory_and_file_exist_on_disk(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """The post directory and index.md file should exist on disk."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Disk Check Post",
                "body": "Content for disk check.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        full_path = app_settings.content_dir / file_path
        assert full_path.exists(), f"File should exist at {full_path}"
        assert full_path.is_file()
        # The parent directory should also exist
        assert full_path.parent.is_dir()
        # The file content should contain the title in front matter
        content = full_path.read_text()
        assert "title: Disk Check Post" in content

    @pytest.mark.asyncio
    async def test_created_post_editable_via_edit_endpoint(self, client: AsyncClient) -> None:
        """A created post should be retrievable via the /edit endpoint."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Edit Roundtrip",
                "body": "Edit me later.\n",
                "labels": ["swe"],
                "is_draft": True,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        edit_resp = await client.get(
            f"/api/posts/{file_path}/edit",
            headers=headers,
        )
        assert edit_resp.status_code == 200
        data = edit_resp.json()
        assert data["title"] == "Edit Roundtrip"
        assert data["file_path"] == file_path
        assert data["labels"] == ["swe"]
        assert data["is_draft"] is True

    @pytest.mark.asyncio
    async def test_create_post_with_special_characters_in_title(self, client: AsyncClient) -> None:
        """Titles with special characters should produce valid slug-based paths."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "What's the Best Approach? (Part 1)",
                "body": "Content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]
        assert file_path.startswith("posts/")
        assert file_path.endswith("/index.md")
        # Should not contain special characters in the path
        dir_name = file_path.split("/")[1]
        assert "'" not in dir_name
        assert "?" not in dir_name
        assert "(" not in dir_name


class TestPostDirectoryDeletion:
    """Tests for deleting directory-based posts with and without assets."""

    @pytest.mark.asyncio
    async def test_delete_with_assets_removes_directory(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """DELETE with delete_assets=true removes entire directory."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Delete Dir Test", "body": "Content", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]
        post_dir = (app_settings.content_dir / file_path).parent

        # Upload an asset
        await client.post(
            f"/api/posts/{file_path}/assets",
            files={"files": ("img.png", b"\x89PNG" + b"\x00" * 10, "image/png")},
            headers=headers,
        )
        assert (post_dir / "img.png").exists()

        resp = await client.delete(
            f"/api/posts/{file_path}?delete_assets=true",
            headers=headers,
        )
        assert resp.status_code == 204
        assert not post_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_without_assets_keeps_directory(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """DELETE without delete_assets keeps directory but removes index.md."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Keep Dir Test", "body": "Content", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]
        post_dir = (app_settings.content_dir / file_path).parent

        # Upload an asset
        await client.post(
            f"/api/posts/{file_path}/assets",
            files={"files": ("img.png", b"\x89PNG" + b"\x00" * 10, "image/png")},
            headers=headers,
        )

        resp = await client.delete(
            f"/api/posts/{file_path}",
            headers=headers,
        )
        assert resp.status_code == 204
        # Directory still exists with the asset
        assert post_dir.exists()
        assert (post_dir / "img.png").exists()
        # But index.md is gone
        assert not (post_dir / "index.md").exists()

    @pytest.mark.asyncio
    async def test_delete_with_assets_cleans_symlinks(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """DELETE with delete_assets=true also removes symlinks pointing to the directory."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Symlink Cleanup", "body": "Content", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert create_resp.status_code == 201
        old_path = create_resp.json()["file_path"]

        # Rename to create a symlink
        update_resp = await client.put(
            f"/api/posts/{old_path}",
            json={
                "title": "Symlink Renamed",
                "body": "Content",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert update_resp.status_code == 200
        new_path = update_resp.json()["file_path"]
        old_dir = (app_settings.content_dir / old_path).parent
        assert old_dir.is_symlink()

        # Delete with assets
        resp = await client.delete(
            f"/api/posts/{new_path}?delete_assets=true",
            headers=headers,
        )
        assert resp.status_code == 204
        # Both the actual directory and the symlink should be gone
        new_dir = (app_settings.content_dir / new_path).parent
        assert not new_dir.exists()
        assert not old_dir.exists()


class TestUnicodePostCreation:
    """Tests for creating posts with unicode/i18n titles."""

    @pytest.mark.asyncio
    async def test_create_post_with_cjk_title(self, client: AsyncClient) -> None:
        """CJK characters are stripped by ASCII encoding, resulting in 'untitled' slug."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "\u65e5\u672c\u8a9e\u30c6\u30b9\u30c8",
                "body": "CJK content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        file_path = data["file_path"]
        assert file_path.startswith("posts/")
        assert file_path.endswith("/index.md")
        # CJK characters are all non-ASCII, so slug falls back to "untitled"
        assert "untitled" in file_path

        # Verify the post is accessible
        get_resp = await client.get(f"/api/posts/{file_path}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "\u65e5\u672c\u8a9e\u30c6\u30b9\u30c8"

    @pytest.mark.asyncio
    async def test_create_post_with_emoji_title(self, client: AsyncClient) -> None:
        """Emoji characters are stripped, leaving only ASCII parts in slug."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Hello \U0001f30d World",
                "body": "Emoji content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        file_path = data["file_path"]
        assert file_path.startswith("posts/")
        assert file_path.endswith("/index.md")
        # Emoji stripped, slug should contain "hello-world"
        assert "hello-world" in file_path

    @pytest.mark.asyncio
    async def test_create_post_with_accented_title(self, client: AsyncClient) -> None:
        """Accented characters are normalized to their ASCII equivalents."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Caf\u00e9 r\u00e9sum\u00e9",
                "body": "Accented content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        file_path = data["file_path"]
        assert file_path.startswith("posts/")
        assert file_path.endswith("/index.md")
        # Accented chars normalized to ASCII: "cafe-resume"
        assert "cafe-resume" in file_path
