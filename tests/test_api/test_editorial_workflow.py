"""Editorial workflow integration tests: full post lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

pytestmark = pytest.mark.slow


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for editorial workflow tests."""
    # Add a label so we can assign it to posts
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.tech]\nnames = ['technology']\n[labels.science]\nnames = ['science']\n"
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
    """Login as admin and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestEditorialWorkflow:
    """Full editorial lifecycle: create -> labels -> preview -> edit -> publish -> delete."""

    @pytest.mark.asyncio
    async def test_full_post_lifecycle(self, client: AsyncClient) -> None:
        # Step 1: Login as admin
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: Create a draft post
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "My Draft Post",
                "body": "Initial draft content.\n",
                "is_draft": True,
                "labels": [],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        file_path = created["file_path"]
        assert created["title"] == "My Draft Post"
        assert created["is_draft"] is True
        assert file_path.startswith("posts/")
        assert file_path.endswith("/index.md")

        # Step 3: Add labels to the post
        label_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "My Draft Post",
                "body": "Initial draft content.\n",
                "is_draft": True,
                "labels": ["tech", "science"],
            },
            headers=headers,
        )
        assert label_resp.status_code == 200
        label_data = label_resp.json()
        assert set(label_data["labels"]) == {"tech", "science"}

        # Step 4: Preview the post content via render endpoint
        preview_resp = await client.post(
            "/api/render/preview",
            json={"markdown": "**Bold** and *italic* content.\n"},
            headers=headers,
        )
        assert preview_resp.status_code == 200
        preview_html = preview_resp.json()["html"]
        assert "<strong>" in preview_html or "<b>" in preview_html
        assert "<em>" in preview_html or "<i>" in preview_html

        # Step 5: Edit the post (update title and body)
        edit_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "My Published Post",
                "body": "Updated and polished content.\n\nWith multiple paragraphs.\n",
                "is_draft": True,
                "labels": ["tech", "science"],
            },
            headers=headers,
        )
        assert edit_resp.status_code == 200
        edited = edit_resp.json()
        assert edited["title"] == "My Published Post"
        # Title change causes a directory rename for index.md posts
        new_file_path = edited["file_path"]

        # Step 6: Publish the post (set is_draft=False)
        publish_resp = await client.put(
            f"/api/posts/{new_file_path}",
            json={
                "title": "My Published Post",
                "body": "Updated and polished content.\n\nWith multiple paragraphs.\n",
                "is_draft": False,
                "labels": ["tech", "science"],
            },
            headers=headers,
        )
        assert publish_resp.status_code == 200
        published = publish_resp.json()
        assert published["is_draft"] is False
        final_file_path = published["file_path"]

        # Step 7: Verify post is publicly visible (GET without auth)
        public_resp = await client.get(f"/api/posts/{final_file_path}")
        assert public_resp.status_code == 200
        public_data = public_resp.json()
        assert public_data["title"] == "My Published Post"
        assert public_data["is_draft"] is False

        # Also verify it appears in the public post list
        list_resp = await client.get("/api/posts")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        titles = [p["title"] for p in list_data["posts"]]
        assert "My Published Post" in titles

        # Step 8: Delete the post
        delete_resp = await client.delete(
            f"/api/posts/{final_file_path}",
            headers=headers,
        )
        assert delete_resp.status_code == 204

        # Step 9: Verify it's gone
        gone_resp = await client.get(f"/api/posts/{final_file_path}")
        assert gone_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_not_visible_without_auth(self, client: AsyncClient) -> None:
        """Draft posts should not be visible to unauthenticated users."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a draft
        resp = await client.post(
            "/api/posts",
            json={
                "title": "Secret Draft",
                "body": "This is secret.\n",
                "is_draft": True,
                "labels": [],
            },
            headers=headers,
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        # Try to access without auth - should be 404 (hidden)
        unauth_resp = await client.get(f"/api/posts/{file_path}")
        assert unauth_resp.status_code == 404

        # Drafts should not appear in unauthenticated post list
        list_resp = await client.get("/api/posts")
        list_data = list_resp.json()
        titles = [p["title"] for p in list_data["posts"]]
        assert "Secret Draft" not in titles

        # Clean up
        await client.delete(f"/api/posts/{file_path}", headers=headers)
