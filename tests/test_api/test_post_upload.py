"""Tests for post upload endpoint."""

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
def upload_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
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
async def client(upload_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(upload_settings) as ac:
        yield ac


async def login(client: AsyncClient) -> str:
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    return resp.json()["access_token"]


class TestPostUpload:
    @pytest.mark.asyncio
    async def test_upload_single_markdown_file(
        self, client: AsyncClient, upload_settings: Settings
    ) -> None:
        token = await login(client)
        md_content = "---\ntitle: My Uploaded Post\nlabels: []\n---\n\nHello world!\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("my-post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Uploaded Post"
        assert "index.md" in data["file_path"]
        assert "my-uploaded-post" in data["file_path"]
        assert (upload_settings.content_dir / data["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_upload_markdown_with_heading_title(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = "# Great Heading\n\nBody text here.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Great Heading"

    @pytest.mark.asyncio
    async def test_upload_no_title_returns_422(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = "Just some text without any heading or front matter.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "no_title"

    @pytest.mark.asyncio
    async def test_upload_no_title_with_title_param(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = "Just some text without any heading.\n"
        resp = await client.post(
            "/api/posts/upload?title=User%20Provided%20Title",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "User Provided Title"

    @pytest.mark.asyncio
    async def test_upload_folder_with_assets(
        self, client: AsyncClient, upload_settings: Settings
    ) -> None:
        token = await login(client)
        md_content = "---\ntitle: Folder Post\n---\n\n![photo](photo.png)\n"
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        resp = await client.post(
            "/api/posts/upload",
            files=[
                ("files", ("index.md", md_content.encode(), "text/markdown")),
                ("files", ("photo.png", png_bytes, "image/png")),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Folder Post"
        post_dir = (upload_settings.content_dir / data["file_path"]).parent
        assert (post_dir / "photo.png").exists()

    @pytest.mark.asyncio
    async def test_upload_no_markdown_returns_422(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("photo.png", b"\x89PNG", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert "No markdown file" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, client: AsyncClient) -> None:
        md_content = "---\ntitle: Test\n---\nBody\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("test.md", md_content.encode(), "text/markdown")},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_preserves_frontmatter_timestamps(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = (
            "---\ntitle: Timestamped\n"
            "created_at: 2025-01-15 10:30:00+00:00\n"
            "modified_at: 2025-06-20 14:00:00+00:00\n"
            "---\nBody\n"
        )
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created_at"].startswith("2025-01-15T")
        assert data["modified_at"].startswith("2025-06-20T")

    @pytest.mark.asyncio
    async def test_upload_draft_post(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = "---\ntitle: Draft Post\ndraft: true\n---\nDraft body\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["is_draft"] is True

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self, client: AsyncClient) -> None:
        token = await login(client)
        large_md = "---\ntitle: Big\n---\n" + "x" * (11 * 1024 * 1024)
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("big.md", large_md.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_total_size_too_large(self, client: AsyncClient) -> None:
        """Multiple files each under 10 MB but exceeding 50 MB total should be rejected."""
        token = await login(client)
        md_content = "---\ntitle: Multi\n---\nBody\n"
        # 6 files of 9 MB each = 54 MB total, each under per-file limit
        large_asset = b"\x00" * (9 * 1024 * 1024)
        file_list = [("files", ("index.md", md_content.encode(), "text/markdown"))]
        for i in range(6):
            file_list.append(("files", (f"asset{i}.bin", large_asset, "application/octet-stream")))
        resp = await client.post(
            "/api/posts/upload",
            files=file_list,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert "50 MB" in resp.json()["detail"]


class TestAssetUploadAuthorization:
    @pytest.mark.asyncio
    async def test_asset_upload_forbidden_for_non_author(self, client: AsyncClient) -> None:
        """A different user should not be able to upload assets to another user's post."""
        # Admin creates a post
        admin_token = await login(client)
        md_content = "---\ntitle: Admin Post\n---\nBody\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        # Register another user (need CSRF token since admin login set cookies)
        csrf_token: str = client.cookies.get("csrf_token") or ""
        resp = await client.post(
            "/api/auth/register",
            json={"username": "other", "email": "other@test.com", "password": "password1234"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert resp.status_code == 201
        resp = await client.post(
            "/api/auth/login",
            json={"username": "other", "password": "password1234"},
            headers={"X-CSRF-Token": csrf_token},
        )
        other_token = resp.json()["access_token"]

        # Other user tries to upload assets to admin's post
        resp = await client.post(
            f"/api/posts/{file_path}/assets",
            files={"files": ("evil.txt", b"malicious content", "text/plain")},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_asset_upload_allowed_for_author(self, client: AsyncClient) -> None:
        """The post author should be able to upload assets."""
        token = await login(client)
        md_content = "---\ntitle: My Post\n---\nBody\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        resp = await client.post(
            f"/api/posts/{file_path}/assets",
            files={"files": ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "photo.png" in resp.json()["uploaded"]
