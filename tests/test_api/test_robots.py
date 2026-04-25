"""Integration tests for the robots.txt endpoint."""

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
def robots_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
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
async def client(robots_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(robots_settings) as ac:
        yield ac


class TestRobotsTxt:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    async def test_allows_root(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Allow: /" in resp.text

    async def test_disallows_api(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /api/" in resp.text

    async def test_allows_api_content(self, client: AsyncClient) -> None:
        # Public post and page assets are served from /api/content/. They must
        # be crawlable so that <img>, og:image, twitter:image, and search-engine
        # image indexing work — Facebook's scraper otherwise refuses to follow
        # the /post/<slug>/<asset> -> /api/content/posts/... redirect because
        # the redirect target falls under the broader /api/ Disallow.
        resp = await client.get("/robots.txt")
        assert "Allow: /api/content/" in resp.text

    async def test_disallows_admin(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /admin" in resp.text

    async def test_disallows_editor(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /editor/" in resp.text

    async def test_disallows_login(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /login" in resp.text

    async def test_includes_content_signal_preferences(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Content-Signal: ai-train=no, search=yes, ai-input=no" in resp.text

    async def test_includes_sitemap_url(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Sitemap:" in resp.text
        assert "/sitemap.xml" in resp.text
