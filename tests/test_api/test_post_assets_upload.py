"""Tests for POST /api/posts/{file_path}/assets endpoint."""

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
    """Create settings for test app with a sample post."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: Admin\nlabels: []\n---\n\nTest content.\n"
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
    async def test_upload_file_to_existing_post(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        file_content = b"fake image data"

        resp = await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", file_content, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == ["photo.png"]

        # Verify the file actually exists on disk
        uploaded_path = app_settings.content_dir / "posts" / "photo.png"
        assert uploaded_path.exists()
        assert uploaded_path.read_bytes() == file_content

    @pytest.mark.asyncio
    async def test_upload_multiple_files(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[
                ("files", ("a.png", b"data-a", "image/png")),
                ("files", ("b.pdf", b"data-b", "application/pdf")),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["uploaded"]) == {"a.png", "b.pdf"}

        assert (app_settings.content_dir / "posts" / "a.png").exists()
        assert (app_settings.content_dir / "posts" / "b.pdf").exists()

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_to_nonexistent_post(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/posts/posts/nonexistent.md/assets",
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
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("large.bin", large_content, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_invalid_filename_dotfile(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/posts/posts/hello.md/assets",
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
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("subdir/photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        # Directory components should be stripped, only filename kept
        assert data["uploaded"] == ["photo.png"]
        assert (app_settings.content_dir / "posts" / "photo.png").exists()
