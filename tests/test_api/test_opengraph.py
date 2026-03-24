"""Integration tests for Open Graph meta tag injection on /post/ pages."""

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
def og_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for OG tag tests with a published post, a draft, and a frontend dir."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n"
        "This is the post body with some content for the excerpt.\n"
    )
    (posts_dir / "my-draft.md").write_text(
        "---\ntitle: Secret Draft\ncreated_at: 2026-02-02 22:21:29+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\n"
        "Draft content that should not leak.\n"
    )
    # Add a directory-backed post
    dir_post = posts_dir / "my-dir-post"
    dir_post.mkdir()
    (dir_post / "index.md").write_text(
        "---\ntitle: Directory Post Title\ncreated_at: 2026-02-03 10:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "Directory-backed post body for the excerpt.\n"
    )

    # Create a fake frontend dist directory with index.html
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>AgBlogger</title></head>"
        "<body><div id='root'></div></body></html>"
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
async def client(og_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(og_settings) as ac:
        yield ac


class TestPostOgTagsPublished:
    """OG tags are injected for published posts."""

    async def test_og_title_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert 'og:title" content="Hello World"' in resp.text

    async def test_og_description_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert 'og:description"' in resp.text

    async def test_twitter_card_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert 'twitter:card" content="summary"' in resp.text

    async def test_html_title_updated(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert "<title>Hello World</title>" in resp.text

    async def test_og_type_article(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert 'og:type" content="article"' in resp.text

    async def test_og_url_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert 'og:url"' in resp.text
        assert "/post/hello" in resp.text

    async def test_content_type_is_html(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestPostOgTagsMissing:
    """No OG tags for missing posts."""

    async def test_missing_post_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/post/nonexistent")
        assert resp.status_code == 200
        assert "og:title" not in resp.text
        assert "<title>AgBlogger</title>" in resp.text


class TestPostOgTagsDraft:
    """No OG tags leaked for draft posts."""

    async def test_draft_post_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/post/my-draft")
        assert resp.status_code == 200
        assert "og:title" not in resp.text
        assert "Secret Draft" not in resp.text


class TestPostOgTagsDirectoryBacked:
    """OG tags work for directory-backed posts accessed by slug."""

    async def test_og_title_for_directory_post(self, client: AsyncClient) -> None:
        resp = await client.get("/post/my-dir-post")
        assert resp.status_code == 200
        assert 'og:title" content="Directory Post Title"' in resp.text

    async def test_og_url_for_directory_post(self, client: AsyncClient) -> None:
        resp = await client.get("/post/my-dir-post")
        assert resp.status_code == 200
        assert "/post/my-dir-post" in resp.text
