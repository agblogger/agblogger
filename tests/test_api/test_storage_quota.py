"""Tests for content storage quota enforcement."""

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
def quota_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with a small storage quota.

    The quota is set to 50 000 bytes — well above the ~30 KB of git bookkeeping
    that ends up under content_dir during test setup, but small enough that a
    50 000-byte payload pushes total usage over the limit.
    """
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        max_content_size=50_000,
    )


@pytest.fixture
async def client(quota_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(quota_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestPostUploadQuota:
    @pytest.mark.asyncio
    async def test_upload_within_quota_succeeds(self, client: AsyncClient) -> None:
        token = await _login(client)
        md = b"---\ntitle: Small Post\n---\n\nHello.\n"
        resp = await client.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_upload_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        # Create a file large enough to push total usage over the 50 000-byte quota
        md = b"---\ntitle: Big Post\n---\n\n" + b"x" * 50_000
        resp = await client.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"


POST_PATH = "posts/2026-01-01-seed-post/index.md"


@pytest.fixture
def quota_settings_with_post(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with a quota and a pre-existing post."""
    post_dir = tmp_content_dir / "posts" / "2026-01-01-seed-post"
    post_dir.mkdir(parents=True)
    (post_dir / "index.md").write_text(
        "---\ntitle: Seed Post\ncreated_at: 2026-01-01 00:00:00+00\n"
        "author: admin\nlabels: []\n---\n\nSeed.\n"
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
        max_content_size=50_000,
    )


@pytest.fixture
async def client_with_post(
    quota_settings_with_post: Settings,
) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(quota_settings_with_post) as ac:
        yield ac


class TestAssetUploadQuota:
    @pytest.mark.asyncio
    async def test_asset_upload_within_quota_succeeds(self, client_with_post: AsyncClient) -> None:
        token = await _login(client_with_post)
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"x" * 100, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_asset_upload_exceeding_quota_returns_413(
        self, client_with_post: AsyncClient
    ) -> None:
        token = await _login(client_with_post)
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"x" * 50_000, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"


class TestSyncQuota:
    @pytest.mark.asyncio
    async def test_sync_commit_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        big_content = (
            "---\ntitle: Huge Sync Post\ncreated_at: 2026-01-01 00:00:00+00\n"
            "author: admin\nlabels: []\n---\n\n" + "x" * 50_000
        )
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": '{"deleted_files":[],"last_sync_commit":null}'},
            files=[
                (
                    "files",
                    ("posts/2026-01-01-huge/index.md", big_content.encode(), "text/plain"),
                )
            ],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"


class TestCreatePostQuota:
    @pytest.mark.asyncio
    async def test_create_post_within_quota_succeeds(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Small Post",
                "body": "Hello, world.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_post_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Big Post",
                "body": "x" * 50_000,
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"


class TestPageQuota:
    @pytest.mark.asyncio
    async def test_create_page_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "big-page", "title": "Big Page", "body": "x" * 50_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"

    @pytest.mark.asyncio
    async def test_update_page_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        # First create a small page
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "my-page", "title": "My Page"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        # Now update it with content that exceeds the quota
        resp = await client.put(
            "/api/admin/pages/my-page",
            json={"content": "x" * 50_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"

    @pytest.mark.asyncio
    async def test_update_page_that_shrinks_succeeds(self, client: AsyncClient) -> None:
        """Updating a page to make it smaller should always succeed near the quota limit."""
        token = await _login(client)
        # Create a page with substantial content — quota is 50 000 B, git overhead ~26-27 KB,
        # so a 15 000-byte body stays within quota on creation.
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "shrink-page", "title": "Shrink Page", "body": "x" * 15_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        # Now update it to be much smaller — should succeed even though quota was nearly full
        resp = await client.put(
            "/api/admin/pages/shrink-page",
            json={"content": "Short content."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestDeleteFreesQuota:
    @pytest.mark.asyncio
    async def test_delete_post_frees_space_for_new_upload(
        self,
        client_with_post: AsyncClient,
    ) -> None:
        token = await _login(client_with_post)
        # Upload an asset that fills the quota leaving only ~3 500 bytes free
        # (quota=50 000; git init overhead is ~26-27 KB; 20 000 B asset ~= 46 500 B total)
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("big.bin", b"x" * 20_000, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # A further 5 000-byte upload should now be rejected (quota nearly exhausted)
        md_big = b"---\ntitle: Too Big\n---\n\n" + b"x" * 5_000
        resp = await client_with_post.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md_big, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413

        # Delete the post (frees the post directory and its assets)
        resp = await client_with_post.delete(
            f"/api/posts/{POST_PATH}?delete_assets=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        # Now the same 5 000-byte upload should succeed since space was freed
        resp = await client_with_post.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md_big, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201


class TestEditPostQuota:
    @pytest.mark.asyncio
    async def test_edit_that_grows_post_beyond_quota_returns_413(
        self, client_with_post: AsyncClient
    ) -> None:
        """Editing a post to grow it beyond the quota should be rejected."""
        token = await _login(client_with_post)
        resp = await client_with_post.put(
            f"/api/posts/{POST_PATH}",
            json={
                "title": "Seed Post",
                "body": "x" * 50_000,  # exceeds 50_000 byte quota
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"

    @pytest.mark.asyncio
    async def test_edit_that_shrinks_post_succeeds(self, client_with_post: AsyncClient) -> None:
        """Editing a post to make it smaller should always succeed."""
        token = await _login(client_with_post)
        resp = await client_with_post.put(
            f"/api/posts/{POST_PATH}",
            json={
                "title": "Seed Post",
                "body": "Short.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
