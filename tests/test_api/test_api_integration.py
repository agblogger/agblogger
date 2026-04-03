"""Integration tests for the API endpoints."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from backend.version import get_version
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    # Add a sample post
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    no_author_post = posts_dir / "no-author"
    no_author_post.mkdir()
    (no_author_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-03 10:00:00+00\n"
        "labels: []\n---\n# No Author Post\n\nPost without author field.\n"
    )
    # Add a directory-backed post
    dir_post = posts_dir / "dir-post"
    dir_post.mkdir()
    (dir_post / "index.md").write_text(
        "---\ntitle: Directory Post\ncreated_at: 2026-02-04 10:00:00+00\n"
        "author: admin\nlabels: []\n---\n# Dir Post\n\nDirectory-backed content.\n"
    )
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


@pytest.fixture
def dotted_slug_app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings with a nested post whose final slug segment contains a dot."""
    posts_dir = tmp_content_dir / "posts"
    dotted_post = posts_dir / "releases" / "v1.0"
    dotted_post.mkdir(parents=True)
    (dotted_post / "index.md").write_text(
        "---\ntitle: Release v1.0\ncreated_at: 2026-02-05 10:00:00+00\n"
        "author: admin\nlabels: []\n---\n# Release v1.0\n\nRelease notes.\n"
    )
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body><div id='root'></div></body></html>"
    )
    db_path = tmp_path / "dotted-slug.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def dotted_slug_client(dotted_slug_app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client for dotted nested post slug routing."""
    async with create_test_client(dotted_slug_app_settings) as ac:
        yield ac


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == get_version()
        assert data["database"] == "ok"


class TestSiteConfig:
    @pytest.mark.asyncio
    async def test_get_site_config(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages")
        assert resp.status_code == 200
        data = resp.json()
        assert "title" in data
        assert "pages" in data


class TestPosts:
    @pytest.mark.asyncio
    async def test_list_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        assert "posts" in data
        assert "page" in data
        assert "per_page" in data
        assert "total_pages" in data
        assert data["total"] == len(data["posts"])
        titles = [p["title"] for p in data["posts"]]
        assert "Hello World" in titles

    @pytest.mark.asyncio
    async def test_get_post(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/posts/hello/index.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello World"
        assert "rendered_html" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_post(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/posts/nope/index.md")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_post_with_empty_body(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/posts",
            json={
                "title": "Empty Body Post",
                "body": "",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_post_with_minimal_body(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/posts",
            json={
                "title": "Minimal Body Post",
                "body": " ",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        get_resp = await client.get(f"/api/posts/{file_path}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Minimal Body Post"

    @pytest.mark.asyncio
    async def test_pagination_with_many_posts(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        # Create 12 published posts (there are already 3 from fixture = 15 total)
        for i in range(12):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": f"Pagination Post {i:02d}",
                    "body": f"Content for post {i}.\n",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201

        # Request page 1 with per_page=5
        page1_resp = await client.get("/api/posts", params={"page": 1, "per_page": 5})
        assert page1_resp.status_code == 200
        page1_data = page1_resp.json()
        assert page1_data["total"] == 15
        assert len(page1_data["posts"]) == 5

        # Request page 2 with per_page=5
        page2_resp = await client.get("/api/posts", params={"page": 2, "per_page": 5})
        assert page2_resp.status_code == 200
        page2_data = page2_resp.json()
        assert len(page2_data["posts"]) == 5

        # Verify no overlap between pages
        page1_paths = {p["file_path"] for p in page1_data["posts"]}
        page2_paths = {p["file_path"] for p in page2_data["posts"]}
        assert page1_paths.isdisjoint(page2_paths)


class TestLabels:
    @pytest.mark.asyncio
    async def test_list_labels(self, client: AsyncClient) -> None:
        resp = await client.get("/api/labels")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        label = data[0]
        assert "id" in label
        assert "names" in label
        assert "is_implicit" in label
        assert "parents" in label
        assert "children" in label
        assert "post_count" in label
        swe_labels = [lb for lb in data if lb["id"] == "swe"]
        assert len(swe_labels) == 1
        assert swe_labels[0]["names"] == ["software engineering"]
        assert swe_labels[0]["post_count"] >= 1

    @pytest.mark.asyncio
    async def test_label_graph(self, client: AsyncClient) -> None:
        resp = await client.get("/api/labels/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_label_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/labels/nonexistent-label-id")
        assert resp.status_code == 404


class TestAuth:
    @pytest.mark.asyncio
    async def test_login(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["csrf_token"]
        assert "access_token" not in data
        assert "refresh_token" not in data

    @pytest.mark.asyncio
    async def test_login_bad_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_authenticated(self, client: AsyncClient) -> None:
        # Login first
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401


class TestFiltering:
    @pytest.mark.asyncio
    async def test_filter_by_label(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"labels": "swe"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for post in data["posts"]:
            assert "swe" in post["labels"]

    @pytest.mark.asyncio
    async def test_filter_by_author(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"author": "Admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_author_case_insensitive(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"author": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_author_partial_match(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"author": "Adm"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_date_range(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"from": "2026-01-01", "to": "2026-12-31"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_no_results(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"author": "Nonexistent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_label_mode_or(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"labels": "swe", "labelMode": "or"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_label_mode_and(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts", params={"labels": "swe", "labelMode": "and"})
        assert resp.status_code == 200
        # AND with single label same as OR
        data = resp.json()
        assert data["total"] >= 1


class TestSync:
    @pytest.mark.asyncio
    async def test_sync_status(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "to_upload" in data
        assert "to_download" in data
        # Server has files, client has empty manifest, so should see downloads
        assert len(data["to_download"]) >= 1

    @pytest.mark.asyncio
    async def test_sync_status_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/sync/status",
            json={"client_manifest": []},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_download(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/sync/download/posts/hello/index.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert b"Hello World" in resp.content

    @pytest.mark.asyncio
    async def test_sync_download_nonexistent(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/sync/download/nonexistent.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_sync_commit(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": json.dumps({"deleted_files": []})},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # No files uploaded or deleted, so files_synced is 0
        assert data["files_synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_commit_normalizes_frontmatter(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Upload a post with NO front matter via commit
        content = b"# New Synced Post\n\nContent here.\n"
        metadata = json.dumps({"deleted_files": []})
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/synced-new/index.md", io.BytesIO(content), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify the post was cached with normalized timestamps
        resp = await client.get("/api/posts/posts/synced-new/index.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Synced Post"
        assert data["created_at"] is not None
        assert data["modified_at"] is not None

    @pytest.mark.asyncio
    async def test_sync_commit_warns_on_unrecognized_fields(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Upload a post with an unrecognized front matter field via commit
        content = b"---\ncustom_field: hello\n---\n# Post\n\nContent.\n"
        metadata = json.dumps({"deleted_files": []})
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/custom-fields/index.md", io.BytesIO(content), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any("custom_field" in w for w in data["warnings"])

    @pytest.mark.asyncio
    async def test_sync_commit_no_files(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Commit with no files
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": json.dumps({"deleted_files": []})},
            headers=headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sync_commit_deletes_remote_files(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        before_resp = await client.get("/api/sync/download/posts/hello/index.md", headers=headers)
        assert before_resp.status_code == 200

        metadata = json.dumps({"deleted_files": ["posts/hello/index.md"]})
        commit_resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert commit_resp.status_code == 200

        after_resp = await client.get("/api/sync/download/posts/hello/index.md", headers=headers)
        assert after_resp.status_code == 404


class TestCrosspost:
    @pytest.mark.asyncio
    async def test_list_accounts_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/crosspost/accounts")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/crosspost/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_account(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/crosspost/accounts",
            json={
                "platform": "bluesky",
                "account_name": "test.bsky.social",
                "credentials": {"identifier": "test", "password": "secret"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["platform"] == "bluesky"
        assert data["account_name"] == "test.bsky.social"

    @pytest.mark.asyncio
    async def test_crosspost_history_empty(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.get(
            "/api/crosspost/history/posts/hello/index.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []


class TestRender:
    @pytest.mark.asyncio
    async def test_render_preview(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/render/preview",
            json={"markdown": "# Hello\n\nWorld"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "html" in data
        assert "Hello" in data["html"]

    @pytest.mark.asyncio
    async def test_render_preview_with_file_path(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/render/preview",
            json={
                "markdown": "![photo](photo.png)",
                "file_path": "posts/2026-02-20-my-post/index.md",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "/post/2026-02-20-my-post/photo.png" in data["html"]

    @pytest.mark.asyncio
    async def test_render_preview_without_file_path_keeps_relative(
        self, client: AsyncClient
    ) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/render/preview",
            json={"markdown": "![photo](photo.png)"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "/api/content/" not in data["html"]
        assert "photo.png" in data["html"]

    @pytest.mark.asyncio
    async def test_render_preview_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/render/preview",
            json={"markdown": "# Hello\n\nWorld"},
        )
        assert resp.status_code == 401


class TestPostCRUD:
    @pytest.mark.asyncio
    async def test_create_post_authenticated(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/posts",
            json={
                "title": "New Post",
                "body": "Content here.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "New Post"

    @pytest.mark.asyncio
    async def test_create_post_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/posts",
            json={
                "title": "No Auth",
                "body": "Content.\n",
                "labels": [],
                "is_draft": False,
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_post_authenticated(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Hello World Updated",
                "body": "Updated content.\n",
                "labels": ["swe"],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Hello World Updated"

    @pytest.mark.asyncio
    async def test_update_nonexistent_post_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/posts/posts/nope/index.md",
            json={
                "title": "Nope",
                "body": "Content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_post_authenticated(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        # Create a post to delete
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Delete Me",
                "body": "Content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        file_path = create_resp.json()["file_path"]

        resp = await client.delete(
            f"/api/posts/{file_path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_post_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.delete(
            "/api/posts/posts/nope/index.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_post_for_edit(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/posts/posts/hello/index.md/edit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "posts/hello/index.md"
        assert data["title"] == "Hello World"
        assert "# Hello World" not in data["body"]
        assert data["labels"] == ["swe"]
        assert "created_at" in data
        assert "modified_at" in data
        assert data["author"] == "admin"

    @pytest.mark.asyncio
    async def test_get_post_for_edit_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/posts/hello/index.md/edit")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_post_for_edit_not_found(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/posts/posts/nonexistent/index.md/edit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_post_with_title_field(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.post(
            "/api/posts",
            json={
                "title": "My Explicit Title",
                "body": "Content without heading.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "My Explicit Title"

    @pytest.mark.asyncio
    async def test_create_post_title_required(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.post(
            "/api/posts",
            json={
                "body": "Content.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_post_whitespace_title_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.post(
            "/api/posts",
            json={
                "title": "   ",
                "body": "Content.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_post_title_too_long_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.post(
            "/api/posts",
            json={
                "title": "A" * 501,
                "body": "Content.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_post_for_edit_returns_title(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.get(
            "/api/posts/posts/hello/index.md/edit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello World"

    @pytest.mark.asyncio
    async def test_update_post_with_title_field(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Updated Title",
                "body": "Updated content.",
                "labels": ["swe"],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_create_post_structured(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/posts",
            json={
                "title": "Structured Post",
                "body": "Content here.",
                "labels": ["swe"],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Structured Post"
        assert data["labels"] == ["swe"]
        assert data["is_draft"] is False
        assert data["author"] == "admin"  # display_name defaults to username

    @pytest.mark.asyncio
    async def test_update_post_structured(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Hello World Structured",
                "body": "Updated structured content.\n",
                "labels": ["swe"],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello World Structured"
        assert data["labels"] == ["swe"]

    @pytest.mark.asyncio
    async def test_update_backfills_author_when_missing(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/posts/posts/no-author/index.md",
            json={
                "title": "No Author Post",
                "body": "Edited content.",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["author"] == "admin"  # backfilled from editing user

    @pytest.mark.asyncio
    async def test_create_and_edit_roundtrip(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        # Create a post with labels and draft
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Roundtrip",
                "body": "Verify all fields survive.",
                "labels": ["swe"],
                "is_draft": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        file_path = create_resp.json()["file_path"]

        # Retrieve via /edit and verify all fields round-tripped
        resp = await client.get(
            f"/api/posts/{file_path}/edit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == file_path
        assert data["title"] == "Roundtrip"
        assert "Verify all fields survive." in data["body"]
        assert "# Roundtrip" not in data["body"]
        assert data["labels"] == ["swe"]
        assert data["is_draft"] is True
        assert data["author"] == "admin"
        assert data["created_at"] is not None
        assert data["modified_at"] is not None

    @pytest.mark.asyncio
    async def test_create_draft_post(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/posts",
            json={
                "title": "Draft Post",
                "body": "This is a draft.",
                "labels": [],
                "is_draft": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_draft"] is True
        file_path = data["file_path"]

        # Verify via /edit endpoint
        edit_resp = await client.get(
            f"/api/posts/{file_path}/edit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["is_draft"] is True

    @pytest.mark.asyncio
    async def test_create_post_updates_label_filter_cache(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "cache-create"}, headers=headers)
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Cache Create",
                "body": "Body.\n",
                "labels": ["cache-create"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        filtered_resp = await client.get("/api/posts", params={"labels": "cache-create"})
        assert filtered_resp.status_code == 200
        filtered_paths = [post["file_path"] for post in filtered_resp.json()["posts"]]
        assert created_file_path in filtered_paths

        label_resp = await client.get("/api/labels/cache-create")
        assert label_resp.status_code == 200
        assert label_resp.json()["post_count"] == 1

    @pytest.mark.asyncio
    async def test_update_post_updates_label_filter_cache(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "cache-update"}, headers=headers)
        update_resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Hello World",
                "body": "Retagged.\n",
                "labels": ["cache-update"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert update_resp.status_code == 200
        updated_file_path = update_resp.json()["file_path"]

        new_label_resp = await client.get("/api/posts", params={"labels": "cache-update"})
        assert new_label_resp.status_code == 200
        new_label_paths = [post["file_path"] for post in new_label_resp.json()["posts"]]
        assert updated_file_path in new_label_paths

        old_label_resp = await client.get("/api/posts", params={"labels": "swe"})
        assert old_label_resp.status_code == 200
        old_label_paths = [post["file_path"] for post in old_label_resp.json()["posts"]]
        assert updated_file_path not in old_label_paths


class TestLabelCRUD:
    @pytest.mark.asyncio
    async def test_create_label(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/labels",
            json={"id": "cooking"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "cooking"
        assert data["names"] == []

    @pytest.mark.asyncio
    async def test_create_label_preserves_explicit_empty_names(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/labels",
            json={"id": "untitled", "names": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["names"] == []

    @pytest.mark.asyncio
    async def test_create_label_duplicate_returns_409(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        # swe already exists from fixture
        resp = await client.post(
            "/api/labels",
            json={"id": "swe"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_label_invalid_id_returns_422(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        # Uppercase not allowed
        resp = await client.post(
            "/api/labels",
            json={"id": "UPPER"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

        # Leading hyphen not allowed
        resp = await client.post(
            "/api/labels",
            json={"id": "-starts-bad"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

        # Spaces not allowed
        resp = await client.post(
            "/api/labels",
            json={"id": "has spaces"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_label_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/labels",
            json={"id": "nope"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_label_with_parents(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/labels",
            json={"id": "new-child", "names": ["new child"], "parents": ["swe"]},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["parents"] == ["swe"]
        assert data["names"] == ["new child"]

    @pytest.mark.asyncio
    async def test_create_label_nonexistent_parent_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/labels",
            json={"id": "orphan-child", "parents": ["nonexistent"]},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_label_parents(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create parent labels
        await client.post("/api/labels", json={"id": "math"}, headers=headers)
        await client.post("/api/labels", json={"id": "physics"}, headers=headers)

        # Create child with one parent
        await client.post(
            "/api/labels",
            json={"id": "quantum", "parents": ["math"]},
            headers=headers,
        )

        # Update to have two parents
        resp = await client.put(
            "/api/labels/quantum",
            json={"names": ["quantum mechanics"], "parents": ["math", "physics"]},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["parents"]) == {"math", "physics"}
        assert data["names"] == ["quantum mechanics"]

    @pytest.mark.asyncio
    async def test_update_label_allows_empty_names(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/labels",
            json={"id": "bare", "names": ["Bare"]},
            headers=headers,
        )

        resp = await client.put(
            "/api/labels/bare",
            json={"names": [], "parents": []},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["names"] == []

        get_resp = await client.get("/api/labels/bare")
        assert get_resp.status_code == 200
        assert get_resp.json()["names"] == []

    @pytest.mark.asyncio
    async def test_update_label_cycle_returns_409(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "top"}, headers=headers)
        await client.post(
            "/api/labels",
            json={"id": "bottom", "parents": ["top"]},
            headers=headers,
        )

        # Try to make top a child of bottom (cycle)
        resp = await client.put(
            "/api/labels/top",
            json={"names": ["top"], "parents": ["bottom"]},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update_label_nonexistent_parent_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "orphan"}, headers=headers)
        resp = await client.put(
            "/api/labels/orphan",
            json={"names": ["orphan"], "parents": ["nonexistent"]},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_label_not_found_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put(
            "/api/labels/nonexistent",
            json={"names": ["nope"], "parents": []},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_label_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/labels/swe",
            json={"names": ["swe"], "parents": []},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_label(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "temp"}, headers=headers)
        resp = await client.delete("/api/labels/temp", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        resp = await client.get("/api/labels/temp")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_label_with_edges_cleans_up(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create A -> B -> C
        await client.post("/api/labels", json={"id": "chain-a"}, headers=headers)
        await client.post(
            "/api/labels",
            json={"id": "chain-b", "parents": ["chain-a"]},
            headers=headers,
        )
        await client.post(
            "/api/labels",
            json={"id": "chain-c", "parents": ["chain-b"]},
            headers=headers,
        )

        # Delete the middle label
        resp = await client.delete("/api/labels/chain-b", headers=headers)
        assert resp.status_code == 200

        # Verify chain-a no longer lists chain-b as child
        resp = await client.get("/api/labels/chain-a")
        assert resp.status_code == 200
        assert "chain-b" not in resp.json()["children"]

        # Verify chain-c no longer lists chain-b as parent
        resp = await client.get("/api/labels/chain-c")
        assert resp.status_code == 200
        assert "chain-b" not in resp.json()["parents"]

        # Graph should not contain chain-b or 500 error
        resp = await client.get("/api/labels/graph")
        assert resp.status_code == 200
        node_ids = [n["id"] for n in resp.json()["nodes"]]
        assert "chain-b" not in node_ids

    @pytest.mark.asyncio
    async def test_create_label_cycle_returns_409(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post("/api/labels", json={"id": "cyc-a"}, headers=headers)
        await client.post(
            "/api/labels",
            json={"id": "cyc-b", "parents": ["cyc-a"]},
            headers=headers,
        )

        # Create cyc-c with parent cyc-b, then try to make cyc-a's parent cyc-c
        await client.post(
            "/api/labels",
            json={"id": "cyc-c", "parents": ["cyc-b"]},
            headers=headers,
        )
        resp = await client.put(
            "/api/labels/cyc-a",
            json={"names": ["A"], "parents": ["cyc-c"]},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_label_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/labels/swe")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_nonexistent_label_returns_404(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.delete("/api/labels/nonexistent", headers=headers)
        assert resp.status_code == 404


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_matching_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/search", params={"q": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "Hello" in data[0]["title"]

    @pytest.mark.asyncio
    async def test_search_no_results(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_reflects_post_create(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Search Fresh",
                "body": "uniquekeycreate987\n",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        search_resp = await client.get("/api/posts/search", params={"q": "uniquekeycreate987"})
        assert search_resp.status_code == 200
        file_paths = [result["file_path"] for result in search_resp.json()]
        assert created_file_path in file_paths

    @pytest.mark.asyncio
    async def test_search_reflects_post_update(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        update_resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Hello World",
                "body": "uniquekeyupdate654\n",
                "labels": ["swe"],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert update_resp.status_code == 200
        updated_file_path = update_resp.json()["file_path"]

        search_resp = await client.get("/api/posts/search", params={"q": "uniquekeyupdate654"})
        assert search_resp.status_code == 200
        file_paths = [result["file_path"] for result in search_resp.json()]
        assert updated_file_path in file_paths

    @pytest.mark.asyncio
    async def test_search_special_characters(self, client: AsyncClient) -> None:
        """Search with special characters should not crash."""
        resp_cpp = await client.get("/api/posts/search", params={"q": "C++"})
        assert resp_cpp.status_code == 200
        assert isinstance(resp_cpp.json(), list)

        resp_quotes = await client.get("/api/posts/search", params={"q": 'hello "world"'})
        assert resp_quotes.status_code == 200
        assert isinstance(resp_quotes.json(), list)

    @pytest.mark.asyncio
    async def test_search_empty_query_rejected(self, client: AsyncClient) -> None:
        """Empty search query should be rejected with 422."""
        resp = await client.get("/api/posts/search", params={"q": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_whitespace_only_returns_empty(self, client: AsyncClient) -> None:
        """Whitespace-only search query should return empty results, not crash."""
        resp = await client.get("/api/posts/search", params={"q": "   "})
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_prefix_matches(self, client: AsyncClient) -> None:
        """Searching for 'Hell' should match 'Hello World' via prefix matching."""
        resp = await client.get("/api/posts/search", params={"q": "Hell"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        titles = [r["title"] for r in data]
        assert any("Hello" in t for t in titles)

    @pytest.mark.asyncio
    async def test_search_prefix_multi_word(self, client: AsyncClient) -> None:
        """Searching for 'Hell Wor' should match 'Hello World' via prefix matching."""
        resp = await client.get("/api/posts/search", params={"q": "Hell Wor"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        titles = [r["title"] for r in data]
        assert any("Hello" in t for t in titles)

    @pytest.mark.asyncio
    async def test_search_finds_post_by_subtitle(self, client: AsyncClient) -> None:
        """A post with a distinctive subtitle should be findable via FTS search."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Subtitle Search Test",
                "subtitle": "uniquesubtitlexyz",
                "body": "This body has no special keywords.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created_file_path = create_resp.json()["file_path"]

        search_resp = await client.get("/api/posts/search", params={"q": "uniquesubtitlexyz"})
        assert search_resp.status_code == 200
        results = search_resp.json()
        file_paths = [r["file_path"] for r in results]
        assert created_file_path in file_paths

    @pytest.mark.asyncio
    async def test_search_result_fields_are_correct(self, client: AsyncClient) -> None:
        """Search results must return correct values for all SearchResult fields."""
        resp = await client.get("/api/posts/search", params={"q": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

        hello = next((r for r in data if "Hello" in r["title"]), None)
        assert hello is not None, "Expected to find Hello World post in search results"

        assert isinstance(hello["id"], int)
        assert hello["file_path"] == "posts/hello/index.md"
        assert hello["title"] == "Hello World"
        assert isinstance(hello["created_at"], str)
        assert len(hello["created_at"]) > 0
        assert isinstance(hello["rank"], float)

    @pytest.mark.asyncio
    async def test_search_result_includes_rendered_excerpt(self, client: AsyncClient) -> None:
        """The rendered_excerpt field must be populated when the post has body content."""
        resp = await client.get("/api/posts/search", params={"q": "content"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

        hello = next((r for r in data if "Hello" in r["title"]), None)
        assert hello is not None
        assert hello["rendered_excerpt"] is not None
        assert isinstance(hello["rendered_excerpt"], str)
        assert len(hello["rendered_excerpt"]) > 0


class TestSubtitleRoundtrip:
    """Subtitle create/update roundtrip through the REST API."""

    @pytest.mark.asyncio
    async def test_subtitle_create_read_update_roundtrip(self, client: AsyncClient) -> None:
        """Create a post with a subtitle, read it back, update the subtitle, verify again."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create a post with a subtitle.
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Subtitle Roundtrip Post",
                "subtitle": "Original subtitle",
                "body": "Body content for subtitle roundtrip test.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        # 2. Read the post back and verify subtitle is present and matches.
        get_resp = await client.get(f"/api/posts/{file_path}")
        assert get_resp.status_code == 200
        post_data = get_resp.json()
        assert post_data["subtitle"] == "Original subtitle"

        # 3. Update the post with a different subtitle.
        update_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Subtitle Roundtrip Post",
                "subtitle": "Updated subtitle",
                "body": "Body content for subtitle roundtrip test.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["subtitle"] == "Updated subtitle"

        # 4. Read back again and assert the new subtitle.
        get_resp2 = await client.get(f"/api/posts/{file_path}")
        assert get_resp2.status_code == 200
        assert get_resp2.json()["subtitle"] == "Updated subtitle"

    @pytest.mark.asyncio
    async def test_subtitle_appears_in_list_endpoint(self, client: AsyncClient) -> None:
        """Subtitle must be present in the list endpoint response for a created post."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Listed Subtitle Post",
                "subtitle": "Visible in list",
                "body": "This post subtitle should be visible in the list response.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        list_resp = await client.get("/api/posts")
        assert list_resp.status_code == 200
        posts = list_resp.json()["posts"]
        matching = [p for p in posts if p["file_path"] == file_path]
        assert len(matching) == 1
        assert matching[0]["subtitle"] == "Visible in list"


class TestSyncCycleWarnings:
    @pytest.mark.asyncio
    async def test_sync_commit_returns_cycle_warnings(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Upload a labels.toml with a cycle via commit
        cyclic_toml = (
            "[labels]\n"
            '[labels.a]\nnames = ["A"]\nparents = ["#b"]\n'
            '[labels.b]\nnames = ["B"]\nparents = ["#a"]\n'
        )

        metadata = json.dumps({"deleted_files": []})
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("labels.toml", io.BytesIO(cyclic_toml.encode()), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "warnings" in data
        assert len(data["warnings"]) == 1
        assert "Cycle detected" in data["warnings"][0]

    @pytest.mark.asyncio
    async def test_sync_commit_no_warnings_without_cycles(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": json.dumps({"deleted_files": []})},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["warnings"] == []


class TestSyncSecurity:
    @pytest.mark.asyncio
    async def test_sync_commit_upload_path_traversal_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        metadata = json.dumps({"deleted_files": []})
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("../../../etc/passwd", b"malicious content", "text/plain"),
                ),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_sync_commit_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": json.dumps({"deleted_files": []})},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_commit_deleted_files_path_traversal_rejected(
        self, client: AsyncClient
    ) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        metadata = json.dumps({"deleted_files": ["../../../etc/passwd"]})
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestAdmin:
    @pytest.mark.asyncio
    async def test_get_site_settings_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/site")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_site_settings(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/admin/site",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Blog"
        assert "timezone" in data

    @pytest.mark.asyncio
    async def test_update_site_settings(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/site",
            json={
                "title": "Updated Blog",
                "description": "New desc",
                "timezone": "US/Eastern",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Blog"

        config_resp = await client.get("/api/pages")
        assert config_resp.json()["title"] == "Updated Blog"

    @pytest.mark.asyncio
    async def test_get_admin_pages(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/admin/pages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "pages" in data
        assert len(data["pages"]) >= 1

    @pytest.mark.asyncio
    async def test_create_page(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/admin/pages",
            json={"id": "contact", "title": "Contact"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == "contact"

    @pytest.mark.asyncio
    async def test_create_duplicate_page_returns_409(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/admin/pages",
            json={"id": "dup-page", "title": "Dup"},
            headers=headers,
        )
        resp = await client.post(
            "/api/admin/pages",
            json={"id": "dup-page", "title": "Dup"},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update_page(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/admin/pages",
            json={"id": "editable", "title": "Editable"},
            headers=headers,
        )

        resp = await client.put(
            "/api/admin/pages/editable",
            json={"title": "Updated Title", "content": "# Updated\n\nNew content."},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        get_resp = await client.get("/api/pages/editable")
        assert get_resp.status_code == 200
        page_data = get_resp.json()
        assert page_data["title"] == "Updated Title"
        assert "New content" in page_data["rendered_html"]

    @pytest.mark.asyncio
    async def test_delete_page(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/admin/pages",
            json={"id": "deleteme", "title": "Delete Me"},
            headers=headers,
        )
        resp = await client.delete(
            "/api/admin/pages/deleteme",
            headers=headers,
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_builtin_page_returns_400(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.delete(
            "/api/admin/pages/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_page_order(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/pages/order",
            json={
                "pages": [
                    {"id": "timeline", "title": "Home"},
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        config_resp = await client.get("/api/pages")
        assert config_resp.status_code == 200
        pages = config_resp.json()["pages"]
        page_ids = [p["id"] for p in pages]
        assert "timeline" in page_ids

    @pytest.mark.asyncio
    async def test_change_password(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword123",
                "confirm_password": "newpassword123",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        login2 = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "newpassword123"},
        )
        assert login2.status_code == 200

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword123",
                "confirm_password": "newpassword123",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_change_password_mismatch(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword123",
                "confirm_password": "differentpassword",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestSearchAfterDelete:
    @pytest.mark.asyncio
    async def test_search_does_not_find_deleted_post(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post with a unique keyword
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "FTS Delete Test",
                "body": "uniqueftsdeletekey999\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        # Verify it's searchable
        search_resp = await client.get("/api/posts/search", params={"q": "uniqueftsdeletekey999"})
        assert search_resp.status_code == 200
        assert len(search_resp.json()) >= 1

        # Delete the post
        delete_resp = await client.delete(f"/api/posts/{file_path}", headers=headers)
        assert delete_resp.status_code == 204

        # Verify it's no longer searchable
        search_resp = await client.get("/api/posts/search", params={"q": "uniqueftsdeletekey999"})
        assert search_resp.status_code == 200
        assert search_resp.json() == []


class TestLabelPosts:
    @pytest.mark.asyncio
    async def test_label_posts_returns_matching_posts(self, client: AsyncClient) -> None:
        """GET /api/labels/{label_id}/posts returns posts with that label."""
        resp = await client.get("/api/labels/swe/posts")
        assert resp.status_code == 200
        data = resp.json()
        # Verify PostListResponse structure
        assert "posts" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "total_pages" in data
        # The seed post "Hello World" has label swe
        assert data["total"] >= 1
        titles = [p["title"] for p in data["posts"]]
        assert "Hello World" in titles

    @pytest.mark.asyncio
    async def test_label_posts_nonexistent_label_returns_404(self, client: AsyncClient) -> None:
        """GET /api/labels/nope/posts returns 404 when label does not exist."""
        resp = await client.get("/api/labels/nope/posts")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Label not found"

    @pytest.mark.asyncio
    async def test_label_posts_excludes_descendant_labels(self, client: AsyncClient) -> None:
        """Posts tagged with a child label do NOT appear in the parent label's posts."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a child label under swe
        child_resp = await client.post(
            "/api/labels",
            json={"id": "backend-dev", "names": ["backend development"], "parents": ["swe"]},
            headers=headers,
        )
        assert child_resp.status_code == 201

        # Create a post tagged only with the child label
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Backend Dev Post",
                "body": "A post about backend development.\n",
                "labels": ["backend-dev"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201

        # Query posts for the parent label (swe) -- should NOT include the child's post
        resp = await client.get("/api/labels/swe/posts")
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Backend Dev Post" not in titles

        # But querying the child label directly should include it
        child_resp = await client.get("/api/labels/backend-dev/posts")
        assert child_resp.status_code == 200
        child_data = child_resp.json()
        child_titles = [p["title"] for p in child_data["posts"]]
        assert "Backend Dev Post" in child_titles


class TestPostsIncludeSublabelsParam:
    @pytest.mark.asyncio
    async def test_posts_filter_excludes_sublabels_by_default(self, client: AsyncClient) -> None:
        """GET /api/posts?labels=parent does NOT include child-label posts by default."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create parent and child labels
        await client.post(
            "/api/labels",
            json={"id": "parent-lbl", "names": ["Parent"]},
            headers=headers,
        )
        await client.post(
            "/api/labels",
            json={"id": "child-lbl", "names": ["Child"], "parents": ["parent-lbl"]},
            headers=headers,
        )

        # Create a post tagged with the child only
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Child Only Post",
                "body": "Tagged with child.\n",
                "labels": ["child-lbl"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201

        # Default: should NOT include child-label posts
        resp = await client.get("/api/posts", params={"labels": "parent-lbl"})
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "Child Only Post" not in titles

    @pytest.mark.asyncio
    async def test_posts_filter_includes_sublabels_when_requested(
        self, client: AsyncClient
    ) -> None:
        """GET /api/posts?labels=parent&includeSublabels=true includes child-label posts."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/labels",
            json={"id": "par-sub", "names": ["Parent Sub"]},
            headers=headers,
        )
        await client.post(
            "/api/labels",
            json={"id": "chi-sub", "names": ["Child Sub"], "parents": ["par-sub"]},
            headers=headers,
        )
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Child Sub Post",
                "body": "Tagged with child.\n",
                "labels": ["chi-sub"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201

        # With includeSublabels=true: should include child-label posts
        resp = await client.get(
            "/api/posts",
            params={"labels": "par-sub", "includeSublabels": "true"},
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "Child Sub Post" in titles

    @pytest.mark.asyncio
    async def test_and_mode_exact_match_with_and_without_sublabels(
        self, client: AsyncClient
    ) -> None:
        """AND mode with include_descendants=False only matches exact label IDs."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a parent label "and-par", a child label "and-chi", and an
        # independent label "and-ind".
        await client.post(
            "/api/labels",
            json={"id": "and-par", "names": ["And Parent"]},
            headers=headers,
        )
        await client.post(
            "/api/labels",
            json={"id": "and-chi", "names": ["And Child"], "parents": ["and-par"]},
            headers=headers,
        )
        await client.post(
            "/api/labels",
            json={"id": "and-ind", "names": ["And Independent"]},
            headers=headers,
        )

        # Create a post tagged with the parent and the independent label.
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "And Mode Exact Post",
                "body": "Tagged with and-par and and-ind.\n",
                "labels": ["and-par", "and-ind"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201

        # AND + exact match (includeSublabels=false): post has "and-par" and "and-ind"
        # → should be found.
        resp = await client.get(
            "/api/posts",
            params={
                "labels": "and-par,and-ind",
                "labelMode": "and",
                "includeSublabels": "false",
            },
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "And Mode Exact Post" in titles

        # AND + with sublabels (includeSublabels=true): "and-par" also covers
        # its descendant "and-chi", but the post itself carries "and-par" directly
        # → should still be found.
        resp = await client.get(
            "/api/posts",
            params={
                "labels": "and-par,and-ind",
                "labelMode": "and",
                "includeSublabels": "true",
            },
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "And Mode Exact Post" in titles

        # AND + exact match using the child label the post does NOT carry:
        # querying "and-chi,and-ind" should NOT find the post because the post
        # has "and-par" (the parent), not "and-chi".
        resp = await client.get(
            "/api/posts",
            params={
                "labels": "and-chi,and-ind",
                "labelMode": "and",
                "includeSublabels": "false",
            },
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "And Mode Exact Post" not in titles


class TestPagination:
    @pytest.mark.asyncio
    async def test_pagination_returns_correct_page_metadata(self, client: AsyncClient) -> None:
        """Create 3 posts, request per_page=2, verify pagination metadata."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        for i in range(3):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": f"Pagination Post {i}",
                    "body": f"Content for pagination test {i}.\n",
                    "labels": [],
                    "is_draft": False,
                },
                headers=headers,
            )
            assert resp.status_code == 201

        resp = await client.get("/api/posts", params={"per_page": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 2
        assert len(data["posts"]) == 2
        # Total includes the 3 new posts plus the seed "Hello World" post
        assert data["total"] >= 4
        assert data["total_pages"] >= 2

    @pytest.mark.asyncio
    async def test_pagination_page_2(self, client: AsyncClient) -> None:
        """Page 2 returns different posts than page 1."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        for i in range(3):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": f"Page2 Post {i}",
                    "body": f"Content for page 2 test {i}.\n",
                    "labels": [],
                    "is_draft": False,
                },
                headers=headers,
            )
            assert resp.status_code == 201

        page1_resp = await client.get("/api/posts", params={"per_page": 2, "page": 1})
        page2_resp = await client.get("/api/posts", params={"per_page": 2, "page": 2})
        assert page1_resp.status_code == 200
        assert page2_resp.status_code == 200

        page1_ids = {p["id"] for p in page1_resp.json()["posts"]}
        page2_ids = {p["id"] for p in page2_resp.json()["posts"]}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_pagination_beyond_last_page_returns_empty(self, client: AsyncClient) -> None:
        """Requesting a page beyond the last page returns empty posts list."""
        resp = await client.get("/api/posts", params={"page": 999, "per_page": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["posts"] == []
        assert data["page"] == 999


class TestSorting:
    @pytest.mark.asyncio
    async def test_sort_by_created_at_desc(self, client: AsyncClient) -> None:
        """Default sort returns newer posts first."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp1 = await client.post(
            "/api/posts",
            json={
                "title": "Older Sort Post",
                "body": "Older content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/posts",
            json={
                "title": "Newer Sort Post",
                "body": "Newer content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp2.status_code == 201

        list_resp = await client.get("/api/posts")
        assert list_resp.status_code == 200
        titles = [p["title"] for p in list_resp.json()["posts"]]
        # Newer post should appear before older post in default desc ordering
        assert titles.index("Newer Sort Post") < titles.index("Older Sort Post")

    @pytest.mark.asyncio
    async def test_sort_by_title_asc(self, client: AsyncClient) -> None:
        """Sort by title ascending returns alphabetical ordering."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/posts",
            json={
                "title": "Zebra Title",
                "body": "Zebra content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        await client.post(
            "/api/posts",
            json={
                "title": "Apple Title",
                "body": "Apple content.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )

        list_resp = await client.get(
            "/api/posts", params={"sort": "title", "order": "asc", "per_page": 100}
        )
        assert list_resp.status_code == 200
        titles = [p["title"] for p in list_resp.json()["posts"]]
        assert titles.index("Apple Title") < titles.index("Zebra Title")


class TestSlugResolution:
    """Slug-based post resolution returns the same post as full file_path."""

    async def test_bare_slug_resolves_canonical_post(self, client: AsyncClient) -> None:
        """GET /api/posts/<slug> resolves canonical directory-backed posts."""
        resp = await client.get("/api/posts/hello")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello World"
        assert data["file_path"] == "posts/hello/index.md"

    async def test_bare_slug_resolves_directory_backed(self, client: AsyncClient) -> None:
        """GET /api/posts/<slug> resolves a directory-backed post."""
        resp = await client.get("/api/posts/dir-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Directory Post"
        assert data["file_path"] == "posts/dir-post/index.md"

    async def test_nonexistent_slug_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/nonexistent-slug")
        assert resp.status_code == 404


class TestPostAssetRedirect:
    """Asset requests under /post/<slug>/<file> redirect to content API."""

    async def test_asset_redirects_to_content_api(self, client: AsyncClient) -> None:
        resp = await client.get("/post/dir-post/photo.png", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/api/content/posts/dir-post/photo.png"

    async def test_nested_asset_redirects(self, client: AsyncClient) -> None:
        resp = await client.get("/post/dir-post/img/photo.png", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/api/content/posts/dir-post/img/photo.png"


class TestDottedNestedPostRoute:
    """Nested post slugs ending in a dotted segment still render the post route."""

    async def test_dotted_nested_slug_does_not_redirect_to_content_api(
        self, dotted_slug_client: AsyncClient
    ) -> None:
        resp = await dotted_slug_client.get("/post/releases/v1.0", follow_redirects=False)
        assert resp.status_code == 200
        assert "/api/content/posts/releases/v1.0" not in resp.text
