"""Tests for draft post visibility restrictions.

Draft posts should only be visible to their author. This includes:
- Post listings (GET /api/posts)
- Post detail (GET /api/posts/{path})
- Post edit (GET /api/posts/{path}/edit)
- Content file serving (GET /api/content/{path})
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client, create_test_user

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

from pathlib import Path


@pytest.fixture
def draft_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for draft visibility tests."""
    # Define a label for label-posts draft visibility tests
    (tmp_content_dir / "labels.toml").write_text(
        '[labels]\n\n[labels.test-label]\nnames = ["Test Label"]\n'
    )

    # Add a published post by Admin
    posts_dir = tmp_content_dir / "posts"
    published_dir = posts_dir / "published"
    published_dir.mkdir()
    (published_dir / "index.md").write_text(
        "---\ntitle: Published Post\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: admin\nlabels: [test-label]\n---\nPublished content.\n"
    )
    # Add a draft post by Admin
    admin_draft_dir = posts_dir / "admin-draft"
    admin_draft_dir.mkdir()
    (admin_draft_dir / "index.md").write_text(
        "---\ntitle: Admin Draft\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: admin\nlabels: [test-label]\ndraft: true\n---\nDraft content.\n"
    )
    (admin_draft_dir / "photo.png").write_bytes(b"fake-draft-asset")
    # Add a draft post directory with an image asset
    draft_dir = posts_dir / "draft-with-asset"
    draft_dir.mkdir()
    (draft_dir / "index.md").write_text(
        "---\ntitle: Draft With Asset\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\nDraft with image.\n"
    )
    (draft_dir / "photo.png").write_bytes(b"fake-png-data")
    # Add a published post directory with an image asset
    pub_dir = posts_dir / "published-with-asset"
    pub_dir.mkdir()
    (pub_dir / "index.md").write_text(
        "---\ntitle: Published With Asset\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: admin\nlabels: []\n---\nPublished with image.\n"
    )
    (pub_dir / "banner.png").write_bytes(b"fake-banner-png")

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
async def client(draft_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client."""
    async with create_test_client(draft_settings) as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> str:
    """Login and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_and_login(client: AsyncClient, username: str, email: str, password: str) -> str:
    """Create a new user and return access token."""
    await create_test_user(client, username, email, password)
    return await _login(client, username, password)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestDraftListingVisibility:
    """Draft posts should only appear in listings for the author."""

    @pytest.mark.asyncio
    async def test_draft_not_in_public_listing(self, client: AsyncClient) -> None:
        """Unauthenticated users should not see draft posts in listings."""
        resp = await client.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles
        assert "Draft With Asset" not in titles

    @pytest.mark.asyncio
    async def test_draft_in_listing_for_author(self, client: AsyncClient) -> None:
        """The author should see their own drafts in listings."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" in titles
        assert "Draft With Asset" in titles

    @pytest.mark.asyncio
    async def test_draft_not_in_listing_for_other_user(self, client: AsyncClient) -> None:
        """A different authenticated user should not see another user's drafts."""
        token = await _register_and_login(client, "other", "other@test.com", "password1234")
        resp = await client.get("/api/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles
        assert "Draft With Asset" not in titles


class TestDraftDetailVisibility:
    """Draft post detail endpoint should restrict access to the author."""

    @pytest.mark.asyncio
    async def test_draft_get_returns_404_for_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated users get 404 for draft posts."""
        resp = await client.get("/api/posts/posts/admin-draft/index.md")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_get_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A different authenticated user gets 404 for another user's draft."""
        token = await _register_and_login(client, "other2", "other2@test.com", "password1234")
        resp = await client.get(
            "/api/posts/posts/admin-draft/index.md",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_get_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access their own draft."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/posts/posts/admin-draft/index.md",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Admin Draft"


class TestDraftEditVisibility:
    """Draft post edit endpoint should restrict access to the author."""

    @pytest.mark.asyncio
    async def test_draft_edit_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A non-admin authenticated user is forbidden from using draft edit endpoint."""
        token = await _register_and_login(client, "other3", "other3@test.com", "password1234")
        resp = await client.get(
            "/api/posts/posts/admin-draft/index.md/edit",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_draft_edit_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access their own draft for editing."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/posts/posts/admin-draft/index.md/edit",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Admin Draft"


class TestDraftContentFileVisibility:
    """Content file serving should restrict draft post assets to the author."""

    @pytest.mark.asyncio
    async def test_draft_asset_returns_404_for_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated users get 404 for draft post assets."""
        resp = await client.get("/api/content/posts/draft-with-asset/photo.png")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_asset_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        """A different authenticated user gets 404 for draft post assets."""
        token = await _register_and_login(client, "other4", "other4@test.com", "password1234")
        resp = await client.get(
            "/api/content/posts/draft-with-asset/photo.png",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_asset_returns_200_for_author(self, client: AsyncClient) -> None:
        """The author can access assets in their draft post directories."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/content/posts/draft-with-asset/photo.png",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_published_asset_accessible_without_auth(self, client: AsyncClient) -> None:
        """Assets for published posts remain publicly accessible."""
        resp = await client.get("/api/content/posts/published-with-asset/banner.png")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_renamed_draft_asset_old_symlink_path_returns_404_when_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Old symlink paths for renamed drafts must not bypass draft asset checks."""
        token = await _login(client, "admin", "admin123")
        headers = _auth_headers(token)

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Private Rename",
                "body": "Secret draft",
                "labels": [],
                "is_draft": True,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        original_path = create_resp.json()["file_path"]

        asset_resp = await client.post(
            f"/api/posts/{original_path}/assets",
            files={"files": ("secret.txt", b"draft-secret", "text/plain")},
            headers=headers,
        )
        assert asset_resp.status_code == 200

        rename_resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Private Rename Updated",
                "body": "Secret draft",
                "labels": [],
                "is_draft": True,
            },
            headers=headers,
        )
        assert rename_resp.status_code == 200

        old_asset_path = f"{Path(original_path).parent}/secret.txt"
        leaked_resp = await client.get(f"/api/content/{old_asset_path}")
        assert leaked_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_orphaned_draft_asset_returns_404_after_default_delete(
        self, client: AsyncClient
    ) -> None:
        """Deleting only a draft index must not leave its assets publicly readable."""
        token = await _login(client, "admin", "admin123")
        headers = _auth_headers(token)

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Private Delete",
                "body": "Secret draft",
                "labels": [],
                "is_draft": True,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        asset_resp = await client.post(
            f"/api/posts/{file_path}/assets",
            files={"files": ("secret.txt", b"draft-secret", "text/plain")},
            headers=headers,
        )
        assert asset_resp.status_code == 200

        delete_resp = await client.delete(f"/api/posts/{file_path}", headers=headers)
        assert delete_resp.status_code == 204

        asset_path = f"{Path(file_path).parent}/secret.txt"
        leaked_resp = await client.get(f"/api/content/{asset_path}")
        assert leaked_resp.status_code == 404


class TestRenamedDraftRedirectVisibility:
    """Renamed draft post redirects must preserve draft confidentiality."""

    @staticmethod
    async def _create_and_rename_draft(
        client: AsyncClient,
        headers: dict[str, str],
    ) -> tuple[str, str]:
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Private Redirect Source",
                "body": "Secret draft",
                "labels": [],
                "is_draft": True,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        original_path = create_resp.json()["file_path"]

        rename_resp = await client.put(
            f"/api/posts/{original_path}",
            json={
                "title": "Private Redirect Target",
                "body": "Secret draft",
                "labels": [],
                "is_draft": True,
            },
            headers=headers,
        )
        assert rename_resp.status_code == 200
        return original_path, rename_resp.json()["file_path"]

    @pytest.mark.asyncio
    async def test_renamed_draft_old_api_path_returns_404_for_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated callers must not learn the renamed draft path."""
        token = await _login(client, "admin", "admin123")
        original_path, _new_path = await self._create_and_rename_draft(
            client,
            _auth_headers(token),
        )

        leaked_resp = await client.get(f"/api/posts/{original_path}", follow_redirects=False)

        assert leaked_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_renamed_draft_old_api_path_returns_404_for_wrong_user(
        self, client: AsyncClient
    ) -> None:
        """A different authenticated user must not learn the renamed draft path."""
        token = await _login(client, "admin", "admin123")
        original_path, _new_path = await self._create_and_rename_draft(
            client,
            _auth_headers(token),
        )
        other_token = await _register_and_login(client, "other5", "other5@test.com", "password1234")

        leaked_resp = await client.get(
            f"/api/posts/{original_path}",
            headers=_auth_headers(other_token),
            follow_redirects=False,
        )

        assert leaked_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_renamed_draft_old_api_path_redirects_for_author(
        self, client: AsyncClient
    ) -> None:
        """The draft author may use the compatibility redirect for renamed drafts."""
        token = await _login(client, "admin", "admin123")
        original_path, new_path = await self._create_and_rename_draft(
            client,
            _auth_headers(token),
        )

        redirect_resp = await client.get(
            f"/api/posts/{original_path}",
            headers=_auth_headers(token),
            follow_redirects=False,
        )

        assert redirect_resp.status_code == 301
        new_slug = new_path.removeprefix("posts/").removesuffix("/index.md")
        assert redirect_resp.headers["location"] == f"/post/{new_slug}"
        assert redirect_resp.headers["cache-control"] == "private, no-store"


class TestDraftAssetAccess:
    """Assets inside a draft post directory must be gated to the post's author."""

    @pytest.mark.asyncio
    async def test_draft_asset_returns_404_for_unauthenticated_user(
        self, client: AsyncClient
    ) -> None:
        """An unauthenticated user cannot access an asset inside a draft post directory."""
        resp = await client.get("/api/content/posts/admin-draft/photo.png")
        assert resp.status_code == 404


class TestDraftLabelPostsVisibility:
    """Draft posts should respect visibility rules in label_posts endpoint."""

    @pytest.mark.asyncio
    async def test_draft_not_in_label_posts_for_anonymous(self, client: AsyncClient) -> None:
        """Unauthenticated users should not see drafts in label-filtered post listings."""
        resp = await client.get("/api/labels/test-label/posts")
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles

    @pytest.mark.asyncio
    async def test_draft_in_label_posts_for_author(self, client: AsyncClient) -> None:
        """The author should see their own drafts in label-filtered post listings."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/labels/test-label/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" in titles

    @pytest.mark.asyncio
    async def test_draft_not_in_label_posts_for_other_user(self, client: AsyncClient) -> None:
        """A different user should not see another user's drafts in label posts."""
        token = await _register_and_login(client, "viewer", "viewer@test.com", "password1234")
        resp = await client.get("/api/labels/test-label/posts", headers=_auth_headers(token))
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["posts"]]
        assert "Published Post" in titles
        assert "Admin Draft" not in titles
