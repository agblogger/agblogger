"""Tests for label post_count visibility filtering.

Label post_count should only include posts visible to the current user:
- Unauthenticated: only published posts
- Authenticated admin: published posts + drafts
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


@pytest.fixture
def label_count_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings with posts that have labels, some of which are drafts."""
    # Write labels.toml with a test label
    (tmp_content_dir / "labels.toml").write_text('[labels]\n[labels.python]\nnames = ["Python"]\n')

    posts_dir = tmp_content_dir / "posts"

    # Published post with label "python"
    pub1 = posts_dir / "published-one"
    pub1.mkdir()
    (pub1 / "index.md").write_text(
        "---\ntitle: Published One\ncreated_at: 2026-01-01 00:00:00+00\n"
        "author: admin\nlabels: [python]\n---\nContent.\n"
    )

    # Published post with label "python"
    pub2 = posts_dir / "published-two"
    pub2.mkdir()
    (pub2 / "index.md").write_text(
        "---\ntitle: Published Two\ncreated_at: 2026-01-02 00:00:00+00\n"
        "author: admin\nlabels: [python]\n---\nContent.\n"
    )

    # Draft post by admin with label "python"
    draft_admin = posts_dir / "admin-draft"
    draft_admin.mkdir()
    (draft_admin / "index.md").write_text(
        "---\ntitle: Admin Draft\ncreated_at: 2026-01-03 00:00:00+00\n"
        "author: admin\nlabels: [python]\ndraft: true\n---\nDraft content.\n"
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
async def client(label_count_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(label_count_settings) as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestLabelPostCountVisibility:
    """Label post_count should reflect only posts visible to the requesting user."""

    @pytest.mark.asyncio
    async def test_unauthenticated_sees_only_published_count(self, client: AsyncClient) -> None:
        """Unauthenticated user should see post_count=2 (only published posts)."""
        resp = await client.get("/api/labels")
        assert resp.status_code == 200
        labels = resp.json()
        python_label = next(lb for lb in labels if lb["id"] == "python")
        assert python_label["post_count"] == 2

    @pytest.mark.asyncio
    async def test_author_sees_own_drafts_in_count(self, client: AsyncClient) -> None:
        """The draft author should see post_count=3 (published + own draft)."""
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/labels", headers=_auth_headers(token))
        assert resp.status_code == 200
        labels = resp.json()
        python_label = next(lb for lb in labels if lb["id"] == "python")
        assert python_label["post_count"] == 3


class TestSingleLabelPostCountVisibility:
    """GET /api/labels/{id} post_count should also respect visibility."""

    @pytest.mark.asyncio
    async def test_unauthenticated_single_label(self, client: AsyncClient) -> None:
        resp = await client.get("/api/labels/python")
        assert resp.status_code == 200
        assert resp.json()["post_count"] == 2

    @pytest.mark.asyncio
    async def test_author_single_label(self, client: AsyncClient) -> None:
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/labels/python", headers=_auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["post_count"] == 3


class TestLabelGraphPostCountVisibility:
    """GET /api/labels/graph post_count should also respect visibility."""

    @pytest.mark.asyncio
    async def test_unauthenticated_graph(self, client: AsyncClient) -> None:
        resp = await client.get("/api/labels/graph")
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        python_node = next(n for n in nodes if n["id"] == "python")
        assert python_node["post_count"] == 2

    @pytest.mark.asyncio
    async def test_author_graph(self, client: AsyncClient) -> None:
        token = await _login(client, "admin", "admin123")
        resp = await client.get("/api/labels/graph", headers=_auth_headers(token))
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        python_node = next(n for n in nodes if n["id"] == "python")
        assert python_node["post_count"] == 3


class TestAuthSensitiveLabelCacheHeaders:
    """Auth-sensitive label responses must not be shared or stored by caches."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "params"),
        [
            ("/api/labels", None),
            ("/api/labels/graph", None),
            ("/api/labels/python", None),
            ("/api/labels/python/posts", None),
        ],
    )
    async def test_authenticated_label_reads_set_private_cache_headers(
        self,
        client: AsyncClient,
        path: str,
        params: dict[str, str] | None,
    ) -> None:
        token = await _login(client, "admin", "admin123")

        resp = await client.get(path, params=params, headers=_auth_headers(token))

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "private, no-store"
        vary_values = {value.strip().lower() for value in resp.headers["vary"].split(",")}
        assert "authorization" in vary_values
        assert "cookie" in vary_values
