"""Regression tests for S-01: search must include drafts for authenticated admin.

Prior to the fix, search_posts hardcoded AND p.is_draft = 0, so admin
could never find their own drafts via the search endpoint.
"""

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
    """App settings with a minimal content directory."""
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")
    db_path = tmp_path / "test_search_drafts.db"
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
    """HTTP client with full app lifespan (DB + FTS tables set up)."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _create_post(
    client: AsyncClient,
    token: str,
    *,
    title: str,
    body: str = "Some body content.\n",
    is_draft: bool = False,
) -> str:
    """Create a post and return its file_path."""
    resp = await client.post(
        "/api/posts",
        json={"title": title, "body": body, "labels": [], "is_draft": is_draft},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["file_path"]


class TestSearchDraftVisibility:
    """search endpoint respects include_drafts based on auth."""

    @pytest.mark.asyncio
    async def test_unauthenticated_search_excludes_drafts(self, client: AsyncClient) -> None:
        """Anonymous search must NOT return draft posts."""
        token = await _login(client)
        await _create_post(
            client,
            token,
            title="Draft uniquedraftvisibilityword",
            is_draft=True,
        )

        # Unauthenticated search
        resp = await client.get("/api/posts/search", params={"q": "uniquedraftvisibilityword"})
        assert resp.status_code == 200
        file_paths = [r["file_path"] for r in resp.json()]
        assert not file_paths, f"Expected empty results but got: {file_paths}"

    @pytest.mark.asyncio
    async def test_authenticated_search_includes_drafts(self, client: AsyncClient) -> None:
        """Authenticated admin search MUST return draft posts."""
        token = await _login(client)
        draft_path = await _create_post(
            client,
            token,
            title="Draft uniqueauthsearchword",
            is_draft=True,
        )

        resp = await client.get(
            "/api/posts/search",
            params={"q": "uniqueauthsearchword"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        file_paths = [r["file_path"] for r in resp.json()]
        assert draft_path in file_paths, (
            f"Expected draft {draft_path!r} in search results but got: {file_paths}"
        )

    @pytest.mark.asyncio
    async def test_unauthenticated_search_returns_published(self, client: AsyncClient) -> None:
        """Anonymous search returns published posts normally."""
        token = await _login(client)
        pub_path = await _create_post(
            client,
            token,
            title="Published uniquepubsearchword",
            is_draft=False,
        )

        resp = await client.get("/api/posts/search", params={"q": "uniquepubsearchword"})
        assert resp.status_code == 200
        file_paths = [r["file_path"] for r in resp.json()]
        assert pub_path in file_paths

    @pytest.mark.asyncio
    async def test_authenticated_search_returns_both_draft_and_published(
        self, client: AsyncClient
    ) -> None:
        """Authenticated search returns both published and draft posts."""
        token = await _login(client)
        pub_path = await _create_post(
            client, token, title="Published mixedvisibilityword", is_draft=False
        )
        draft_path = await _create_post(
            client, token, title="Draft mixedvisibilityword", is_draft=True
        )

        resp = await client.get(
            "/api/posts/search",
            params={"q": "mixedvisibilityword"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        file_paths = [r["file_path"] for r in resp.json()]
        assert pub_path in file_paths
        assert draft_path in file_paths

    @pytest.mark.asyncio
    async def test_authenticated_search_sets_private_cache_headers(
        self, client: AsyncClient
    ) -> None:
        """Authenticated draft-inclusive search responses must not be cacheable."""
        token = await _login(client)
        await _create_post(
            client,
            token,
            title="Draft uniquecacheheaderword",
            is_draft=True,
        )

        resp = await client.get(
            "/api/posts/search",
            params={"q": "uniquecacheheaderword"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "private, no-store"
        vary_values = {value.strip().lower() for value in resp.headers["vary"].split(",")}
        assert "authorization" in vary_values
        assert "cookie" in vary_values
