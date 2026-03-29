"""Integration tests for the RSS feed endpoint."""

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
def feed_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: []\n---\nHello body.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\nDraft.\n"
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        '<html><head><title>B</title></head><body><div id="root"></div></body></html>'
    )

    db_path = tmp_path / "test.db"
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
async def client(feed_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(feed_settings) as ac:
        yield ac


class TestRssFeed:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert resp.status_code == 200
        assert "application/rss+xml" in resp.headers["content-type"]

    async def test_valid_rss_structure(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert '<?xml version="1.0"' in resp.text
        assert '<rss version="2.0"' in resp.text
        assert "<channel>" in resp.text
        assert "</channel>" in resp.text

    async def test_includes_channel_title(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<title>" in resp.text

    async def test_includes_published_post(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<item>" in resp.text
        assert "Hello World" in resp.text

    async def test_excludes_draft(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "Draft" not in resp.text

    async def test_item_has_link(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "/post/hello" in resp.text

    async def test_item_has_guid(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<guid" in resp.text

    async def test_item_has_pubdate(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<pubDate>" in resp.text

    async def test_atom_self_link(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "atom:link" in resp.text
        assert "/feed.xml" in resp.text
