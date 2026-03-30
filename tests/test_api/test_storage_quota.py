"""Tests for content storage quota enforcement."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import tomli_w

from backend.config import Settings
from backend.filesystem.frontmatter import PostData, serialize_post
from backend.filesystem.toml_manager import PageConfig, parse_site_config
from backend.utils.datetime import now_utc
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def quota_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with a small storage quota.

    The quota is set to 50 000 bytes, which is small enough that a 50 000-byte
    managed-content payload pushes total usage over the limit.
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


def _content_usage(content_dir: Path) -> int:
    return sum(
        path.stat().st_size
        for path in content_dir.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and all(not part.startswith(".") for part in path.relative_to(content_dir).parts)
    )


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

    @pytest.mark.asyncio
    async def test_upload_rejects_when_serialized_post_exceeds_remaining_quota(
        self,
        client_with_post: AsyncClient,
        quota_settings_with_post: Settings,
    ) -> None:
        token = await _login(client_with_post)
        max_size = quota_settings_with_post.max_content_size
        assert max_size is not None

        remaining = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert remaining > 512

        filler_size = remaining - 80
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("fill.bin", b"x" * filler_size, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        tiny_markdown = "# Tiny\n"
        now = now_utc()
        serialized_size = len(
            serialize_post(
                PostData(
                    title="Tiny",
                    content="",
                    raw_content=tiny_markdown,
                    created_at=now,
                    modified_at=now,
                    author="admin",
                    file_path="posts/tiny/index.md",
                )
            ).encode("utf-8")
        )
        raw_size = len(tiny_markdown.encode("utf-8"))

        remaining_after_fill = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert raw_size <= remaining_after_fill < serialized_size

        resp = await client_with_post.post(
            "/api/posts/upload",
            files=[("files", ("index.md", tiny_markdown.encode("utf-8"), "text/markdown"))],
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

    @pytest.mark.asyncio
    async def test_asset_overwrite_near_quota_uses_net_growth(
        self,
        client_with_post: AsyncClient,
        quota_settings_with_post: Settings,
    ) -> None:
        token = await _login(client_with_post)
        max_size = quota_settings_with_post.max_content_size
        assert max_size is not None

        remaining = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert remaining > 1024

        initial_size = remaining - 256
        replacement_size = 512
        assert initial_size > replacement_size

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"x" * initial_size, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"y" * replacement_size, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        asset_path = (
            quota_settings_with_post.content_dir / "posts" / "2026-01-01-seed-post" / "photo.png"
        )
        assert asset_path.read_bytes() == b"y" * replacement_size


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

    @pytest.mark.asyncio
    async def test_sync_commit_allows_delete_then_upload_near_quota(
        self,
        client_with_post: AsyncClient,
        quota_settings_with_post: Settings,
    ) -> None:
        token = await _login(client_with_post)
        headers = {"Authorization": f"Bearer {token}"}
        max_size = quota_settings_with_post.max_content_size
        assert max_size is not None

        remaining = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert remaining > 1024

        existing_size = remaining - 256
        replacement_size = 512
        assert existing_size > replacement_size

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("delete-me.bin", b"x" * existing_size, "application/octet-stream"))],
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await client_with_post.post(
            "/api/sync/commit",
            data={
                "metadata": (
                    '{"deleted_files":["posts/2026-01-01-seed-post/delete-me.bin"],'
                    '"last_sync_commit":null}'
                )
            },
            files=[
                (
                    "files",
                    (
                        "posts/2026-01-01-seed-post/new.bin",
                        b"y" * replacement_size,
                        "application/octet-stream",
                    ),
                )
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        deleted_path = (
            quota_settings_with_post.content_dir
            / "posts"
            / "2026-01-01-seed-post"
            / "delete-me.bin"
        )
        new_path = (
            quota_settings_with_post.content_dir / "posts" / "2026-01-01-seed-post" / "new.bin"
        )
        assert not deleted_path.exists()
        assert new_path.read_bytes() == b"y" * replacement_size

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("follow-up.bin", b"z" * 512, "application/octet-stream"))],
            headers=headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sync_commit_allows_overwrite_near_quota_and_resets_tracker(
        self,
        client_with_post: AsyncClient,
        quota_settings_with_post: Settings,
    ) -> None:
        token = await _login(client_with_post)
        headers = {"Authorization": f"Bearer {token}"}
        max_size = quota_settings_with_post.max_content_size
        assert max_size is not None

        remaining = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert remaining > 1024

        existing_size = remaining - 256
        replacement_size = 512
        assert existing_size > replacement_size

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("replace.bin", b"x" * existing_size, "application/octet-stream"))],
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await client_with_post.post(
            "/api/sync/commit",
            data={"metadata": '{"deleted_files":[],"last_sync_commit":null}'},
            files=[
                (
                    "files",
                    (
                        "posts/2026-01-01-seed-post/replace.bin",
                        b"y" * replacement_size,
                        "application/octet-stream",
                    ),
                )
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        asset_path = (
            quota_settings_with_post.content_dir / "posts" / "2026-01-01-seed-post" / "replace.bin"
        )
        assert asset_path.read_bytes() == b"y" * replacement_size

        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("follow-up.bin", b"z" * 512, "application/octet-stream"))],
            headers=headers,
        )
        assert resp.status_code == 200


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
        # Create a page with substantial content so the next edit runs near the limit.
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

    @pytest.mark.asyncio
    async def test_create_page_rejects_when_index_toml_growth_exceeds_remaining_quota(
        self,
        client: AsyncClient,
        quota_settings: Settings,
    ) -> None:
        token = await _login(client)
        max_size = quota_settings.max_content_size
        assert max_size is not None

        page_id = "tiny-page"
        page_title = "Tiny Page"
        page_body = "x"
        page_size = len(page_body.encode("utf-8"))

        cfg = parse_site_config(quota_settings.content_dir)
        old_index_size = (quota_settings.content_dir / "index.toml").stat().st_size
        updated_cfg = cfg.with_pages(
            [*cfg.pages, PageConfig(id=page_id, title=page_title, file=f"{page_id}.md")]
        )
        projected_index_size = len(
            tomli_w.dumps(
                {
                    "site": {
                        "title": updated_cfg.title,
                        "description": updated_cfg.description,
                        "timezone": updated_cfg.timezone,
                    },
                    "pages": [
                        {
                            key: value
                            for key, value in {
                                "id": page.id,
                                "title": page.title,
                                "file": page.file,
                            }.items()
                            if value is not None
                        }
                        for page in updated_cfg.pages
                    ],
                }
            ).encode("utf-8")
        )
        projected_delta = page_size + (projected_index_size - old_index_size)
        assert projected_delta > page_size

        remaining = max_size - _content_usage(quota_settings.content_dir)
        assert remaining > projected_delta

        filler_body_size = remaining - page_size
        filler_now = now_utc()
        filler_title = "Quota Filler"
        filler_serialized_size = len(
            serialize_post(
                PostData(
                    title=filler_title,
                    content="x" * 1,
                    raw_content="",
                    created_at=filler_now,
                    modified_at=filler_now,
                    author="admin",
                    file_path="posts/filler/index.md",
                )
            ).encode("utf-8")
        )
        filler_body_size = max(1, filler_body_size - (filler_serialized_size - 1))

        resp = await client.post(
            "/api/posts",
            json={
                "title": filler_title,
                "body": "x" * filler_body_size,
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

        remaining_after_fill = max_size - _content_usage(quota_settings.content_dir)
        assert page_size <= remaining_after_fill < projected_delta

        resp = await client.post(
            "/api/admin/pages",
            json={"id": page_id, "title": page_title, "body": page_body},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"


class TestDeleteFreesQuota:
    @pytest.mark.asyncio
    async def test_delete_post_frees_space_for_new_upload(
        self,
        client_with_post: AsyncClient,
        quota_settings_with_post: Settings,
    ) -> None:
        token = await _login(client_with_post)
        max_size = quota_settings_with_post.max_content_size
        assert max_size is not None

        md_big = b"---\ntitle: Too Big\n---\n\n" + b"x" * 5_000
        upload_now = now_utc()
        upload_serialized_size = len(
            serialize_post(
                PostData(
                    title="Too Big",
                    content="",
                    raw_content=md_big.decode("utf-8"),
                    created_at=upload_now,
                    modified_at=upload_now,
                    author="admin",
                    file_path="posts/too-big/index.md",
                )
            ).encode("utf-8")
        )

        seed_post_path = quota_settings_with_post.content_dir / POST_PATH
        seed_post_size = seed_post_path.stat().st_size
        initial_remaining = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert initial_remaining + seed_post_size >= upload_serialized_size

        asset_size = initial_remaining - (upload_serialized_size - 1)
        assert asset_size > 0

        # Fill the managed-content quota so the next upload is one byte over budget.
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("big.bin", b"x" * asset_size, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        remaining_after_fill = max_size - _content_usage(quota_settings_with_post.content_dir)
        assert remaining_after_fill == upload_serialized_size - 1

        # The next upload should be rejected while the seed post and its assets still exist.
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
