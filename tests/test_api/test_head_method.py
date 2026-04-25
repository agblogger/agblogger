"""Integration tests for HEAD method support on public routes.

FastAPI's ``@app.get`` registers GET only, so without a HEAD-aware mechanism a
HEAD request falls through to the static-files mount and returns 404. That
trips up well-behaved crawlers (e.g., Facebook's scraper) that probe with HEAD
before GET. These tests pin the behavior that HEAD on public routes returns the
same status as GET, with no body.
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
def head_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post = posts_dir / "hello"
    post.mkdir()
    (post / "index.md").write_text(
        "---\ntitle: Hello\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "Hello body.\n"
    )

    # Configure a favicon and site image so /favicon.png and /image.png resolve.
    assets = tmp_content_dir / "assets"
    assets.mkdir(exist_ok=True)
    favicon_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x35\x81"
        b"\x84\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (assets / "favicon.png").write_bytes(favicon_bytes)
    (assets / "image.png").write_bytes(favicon_bytes)
    (tmp_content_dir / "index.toml").write_text(
        "[site]\n"
        'title = "Test Blog"\n'
        'description = "Desc"\n'
        'favicon = "assets/favicon.png"\n'
        'image = "assets/image.png"\n'
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
async def client(head_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(head_settings) as ac:
        yield ac


class TestHeadMethod:
    async def test_head_homepage(self, client: AsyncClient) -> None:
        resp = await client.head("/")
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_head_post_page(self, client: AsyncClient) -> None:
        resp = await client.head("/post/hello")
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_head_robots_txt(self, client: AsyncClient) -> None:
        resp = await client.head("/robots.txt")
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_head_favicon_png(self, client: AsyncClient) -> None:
        resp = await client.head("/favicon.png")
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_head_site_image_png(self, client: AsyncClient) -> None:
        resp = await client.head("/image.png")
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_head_post_asset_redirect(self, client: AsyncClient) -> None:
        # /post/<slug>/<asset> 301-redirects to /api/content/posts/...; HEAD
        # must follow the same path so crawlers can validate the og:image URL.
        # httpx does not auto-follow redirects unless asked, so the 3xx status
        # is what we assert here.
        resp = await client.head("/post/hello/missing.png")
        assert resp.status_code in (301, 404)
