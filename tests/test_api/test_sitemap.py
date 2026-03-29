"""Integration tests for the sitemap.xml endpoint."""

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
def sitemap_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: [python]\n---\nBody.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\nDraft.\n"
    )

    labels_toml = tmp_content_dir / "labels.toml"
    labels_toml.write_text('[labels.python]\nnames = ["Python"]\n')

    (tmp_content_dir / "about.md").write_text("# About\nAbout page.\n")
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
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
async def client(sitemap_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(sitemap_settings) as ac:
        yield ac


class TestSitemap:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "application/xml" in resp.headers["content-type"]

    async def test_valid_xml_structure(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert '<?xml version="1.0"' in resp.text
        assert "<urlset" in resp.text
        assert "</urlset>" in resp.text

    async def test_includes_homepage(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "<loc>" in resp.text

    async def test_includes_published_post(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/post/hello" in resp.text

    async def test_excludes_draft(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/post/my-draft" not in resp.text

    async def test_includes_page(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/page/about" in resp.text

    async def test_excludes_builtin_pages_without_files(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/page/timeline" not in resp.text
        assert "/page/labels" not in resp.text

    async def test_includes_label_with_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/labels/python" in resp.text

    async def test_has_lastmod_for_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "<lastmod>" in resp.text
