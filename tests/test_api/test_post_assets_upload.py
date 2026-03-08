"""Tests for POST /api/posts/{file_path}/assets and GET /api/posts/{file_path}/assets endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from backend.config import Settings
from backend.services.upload_limits import MAX_MULTIPART_BODY_SIZE
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


POST_PATH = "posts/2026-02-02-hello-world/index.md"
LEGACY_POST_PATH = "posts/legacy-post.md"


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app with a sample post."""
    posts_dir = tmp_content_dir / "posts"
    hello_post_dir = posts_dir / "2026-02-02-hello-world"
    hello_post_dir.mkdir()
    (hello_post_dir / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: Admin\nauthor_username: admin\nlabels: []\n---\n\nTest content.\n"
    )
    (posts_dir / "legacy-post.md").write_text(
        "---\ntitle: Legacy Post\ncreated_at: 2026-02-03 09:00:00+00\n"
        "author: Admin\nauthor_username: admin\nlabels: []\n---\n\nLegacy content.\n"
    )
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
    """Login and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestUploadAssets:
    @pytest.mark.asyncio
    async def test_rejects_multipart_request_with_excessive_content_length(
        self, client: AsyncClient
    ) -> None:
        token = await _login(client)
        boundary = "test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="photo.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
            "x\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            content=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(MAX_MULTIPART_BODY_SIZE + 1),
            },
        )

        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_file_to_existing_post(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        file_content = b"fake image data"

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == ["photo.png"]

        # Verify the file actually exists on disk
        uploaded_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "photo.png"
        assert uploaded_path.exists()
        assert uploaded_path.read_bytes() == file_content

    @pytest.mark.asyncio
    async def test_upload_multiple_files(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[
                ("files", ("a.png", b"data-a", "image/png")),
                ("files", ("b.pdf", b"data-b", "application/pdf")),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["uploaded"]) == {"a.png", "b.pdf"}

        assert (app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "a.png").exists()
        assert (app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "b.pdf").exists()

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_to_nonexistent_post(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/posts/posts/nonexistent/index.md/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self, client: AsyncClient) -> None:
        token = await _login(client)
        # Create data just over 10 MB
        large_content = b"x" * (10 * 1024 * 1024 + 1)

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("large.bin", large_content, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_invalid_filename_dotfile(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", (".hidden", b"data", "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_strips_directory_components(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)

        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("subdir/photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        # Directory components should be stripped, only filename kept
        assert data["uploaded"] == ["photo.png"]
        uploaded_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "photo.png"
        assert uploaded_path.exists()

    @pytest.mark.asyncio
    async def test_upload_rejects_legacy_flat_file_post(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            f"/api/posts/{LEGACY_POST_PATH}/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 400
        assert "directory-style" in resp.json()["detail"]


class TestListAssets:
    @pytest.mark.asyncio
    async def test_list_assets_empty(self, client: AsyncClient) -> None:
        """GET assets for a post with no assets returns 200 with empty list."""
        token = await _login(client)

        resp = await client.get(
            f"/api/posts/{POST_PATH}/assets",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"] == []

    @pytest.mark.asyncio
    async def test_list_assets_rejects_legacy_flat_file_post(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Legacy flat-file posts do not support editor asset management."""
        token = await _login(client)

        posts_dir = app_settings.content_dir / "posts"
        (posts_dir / "stray-image.png").write_bytes(b"fake png data")

        resp = await client.get(
            f"/api/posts/{LEGACY_POST_PATH}/assets",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 400
        assert "directory-style" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_assets_after_upload(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Upload a file to a directory-style post, then GET assets returns it."""
        token = await _login(client)
        file_content = b"fake image data"

        # Create a directory-style post (only these support co-located assets)
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Asset Test Post", "body": "Some content."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        # Upload an asset
        upload_resp = await client.post(
            f"/api/posts/{created_file_path}/assets",
            files=[("files", ("photo.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200

        # List assets
        resp = await client.get(
            f"/api/posts/{created_file_path}/assets",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["assets"]) == 1
        asset = data["assets"][0]
        assert asset["name"] == "photo.png"
        assert asset["size"] == len(file_content)
        assert asset["is_image"] is True

    @pytest.mark.asyncio
    async def test_list_assets_excludes_index_md(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Create a post-per-directory post, upload asset, index.md not in results."""
        token = await _login(client)

        # Create a post via API (creates post-per-directory)
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Directory Post", "body": "Some content here."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        # Upload an asset to the new post
        upload_resp = await client.post(
            f"/api/posts/{created_file_path}/assets",
            files=[("files", ("diagram.svg", b"<svg></svg>", "image/svg+xml"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200

        # List assets — index.md should NOT appear
        resp = await client.get(
            f"/api/posts/{created_file_path}/assets",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        names = [a["name"] for a in data["assets"]]
        assert "index.md" not in names
        assert "diagram.svg" in names

    @pytest.mark.asyncio
    async def test_list_assets_requires_auth(self, client: AsyncClient) -> None:
        """GET without auth returns 401."""
        resp = await client.get(f"/api/posts/{POST_PATH}/assets")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_assets_nonexistent_post(self, client: AsyncClient) -> None:
        """GET for nonexistent post returns 404."""
        token = await _login(client)

        resp = await client.get(
            "/api/posts/posts/nonexistent/index.md/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestDeleteAsset:
    @pytest.mark.asyncio
    async def test_delete_asset(self, client: AsyncClient, app_settings: Settings) -> None:
        """Upload a file, verify it exists on disk, delete it, verify 204 and gone."""
        token = await _login(client)
        file_content = b"fake image data"

        # Upload an asset
        upload_resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200

        # Verify it exists on disk
        asset_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "photo.png"
        assert asset_path.exists()

        # Delete the asset
        resp = await client.delete(
            f"/api/posts/{POST_PATH}/assets/photo.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        # Verify it's gone from disk
        assert not asset_path.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_asset(self, client: AsyncClient) -> None:
        """DELETE for asset that doesn't exist returns 404."""
        token = await _login(client)

        resp = await client.delete(
            f"/api/posts/{POST_PATH}/assets/nonexistent.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_asset_requires_auth(self, client: AsyncClient) -> None:
        """DELETE without auth returns 401."""
        resp = await client.delete(
            f"/api/posts/{POST_PATH}/assets/photo.png",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cannot_delete_index_md(self, client: AsyncClient) -> None:
        """DELETE index.md returns 400."""
        token = await _login(client)

        # Create a post-per-directory post
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Directory Post", "body": "Some content here."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        # Try to delete index.md
        resp = await client.delete(
            f"/api/posts/{created_file_path}/assets/index.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cannot_delete_hidden_file(self, client: AsyncClient) -> None:
        """DELETE .gitkeep returns 400."""
        token = await _login(client)

        resp = await client.delete(
            f"/api/posts/{POST_PATH}/assets/.gitkeep",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_asset_path_traversal(self, client: AsyncClient) -> None:
        """DELETE with path traversal components is rejected.

        Slash-based traversal (..%2F) is handled at the routing/framework level.
        Backslash traversal is caught by _validate_asset_filename → 400.
        """
        token = await _login(client)

        # Backslash traversal: caught by _validate_asset_filename → 400
        resp = await client.delete(
            f"/api/posts/{POST_PATH}/assets/..%5C..%5Cindex.toml",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


class TestRenameAsset:
    @pytest.mark.asyncio
    async def test_rename_asset(self, client: AsyncClient, app_settings: Settings) -> None:
        """Upload old.png, PATCH rename to new.png, verify old gone and new exists."""
        token = await _login(client)
        file_content = b"fake image data"

        # Upload an asset
        upload_resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("old.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200

        # Rename old.png -> new.png
        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/old.png",
            json={"new_name": "new.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "new.png"
        assert data["size"] == len(file_content)
        assert data["is_image"] is True

        # Verify old file is gone, new file exists
        old_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "old.png"
        new_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "new.png"
        assert not old_path.exists()
        assert new_path.exists()
        assert new_path.read_bytes() == file_content

    @pytest.mark.asyncio
    async def test_rename_to_existing_name(self, client: AsyncClient) -> None:
        """Upload a.png and b.png, try rename a -> b, expect 409."""
        token = await _login(client)

        # Upload two assets
        await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[
                ("files", ("a.png", b"data-a", "image/png")),
                ("files", ("b.png", b"data-b", "image/png")),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/a.png",
            json={"new_name": "b.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_rename_nonexistent_asset(self, client: AsyncClient) -> None:
        """PATCH for asset that doesn't exist returns 404."""
        token = await _login(client)

        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/nonexistent.png",
            json={"new_name": "renamed.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rename_to_invalid_name(self, client: AsyncClient) -> None:
        """Upload, try rename to .hidden, expect 400."""
        token = await _login(client)

        # Upload an asset
        await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/photo.png",
            json={"new_name": ".hidden"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rename_requires_auth(self, client: AsyncClient) -> None:
        """PATCH without auth returns 401."""
        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/photo.png",
            json={"new_name": "new.png"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cannot_rename_to_index_md(self, client: AsyncClient) -> None:
        """Upload, try rename to index.md, expect 400."""
        token = await _login(client)

        # Upload an asset
        await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            f"/api/posts/{POST_PATH}/assets/photo.png",
            json={"new_name": "index.md"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rename_returns_valid_response_when_stat_fails_after_rename(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """Regression: if stat() fails after a successful rename, the endpoint
        should not return 500. The rename already happened — the old filename
        is gone, so retrying would fail. The endpoint should use a fallback size.
        """
        token = await _login(client)
        file_content = b"fake image data"

        # Upload an asset
        upload_resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("old.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200

        # Patch Path.stat to raise OSError (simulating a transient filesystem issue)
        original_stat = type(app_settings.content_dir).stat

        def _broken_stat(self: Path) -> Any:
            if self.name == "new.png":
                raise OSError("simulated stat failure")
            return original_stat(self)

        with patch.object(type(app_settings.content_dir), "stat", _broken_stat):
            resp = await client.patch(
                f"/api/posts/{POST_PATH}/assets/old.png",
                json={"new_name": "new.png"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Should succeed — size was captured before the rename
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["name"] == "new.png"
        assert data["is_image"] is True
        # Size should be the original file size (captured before rename)
        assert data["size"] == len(file_content)

        # Verify the rename actually happened
        old_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "old.png"
        new_path = app_settings.content_dir / "posts" / "2026-02-02-hello-world" / "new.png"
        assert not old_path.exists()
        assert new_path.exists()
