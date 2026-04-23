"""Integration tests for Open Graph meta tag injection on /post/ pages."""

from __future__ import annotations

import re
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
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n"
        "This is the post body with some content for the excerpt.\n"
    )
    unsafe_post = posts_dir / "unsafe"
    unsafe_post.mkdir()
    (unsafe_post / "index.md").write_text(
        "---\ntitle: Unsafe Body\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n"
        "Safe intro.\n\n"
        "[click](javascript:alert('xss'))\n\n"
        "<script>alert('owned')</script>\n\n"
        "Safe outro.\n"
    )
    draft_post = posts_dir / "my-draft"
    draft_post.mkdir()
    (draft_post / "index.md").write_text(
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
    nested_post = posts_dir / "2026" / "recap"
    nested_post.mkdir(parents=True)
    (nested_post / "index.md").write_text(
        "---\ntitle: Nested Recap\ncreated_at: 2026-02-04 10:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "Nested directory-backed post body.\n"
    )

    # Create a fake frontend dist directory with index.html
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>AgBlogger</title></head>"
        '<body><div id="root"></div></body></html>'
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


def _extract_root_fragment(html: str) -> str:
    match = re.search(
        r'<div id="root">(.*?)</div>\s*<script id="__initial_data__"',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


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

    async def test_canonical_file_path_does_not_resolve_as_public_post_url(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/post/posts/hello/index.md")
        assert resp.status_code == 200
        assert "og:title" not in resp.text
        assert "Hello World" not in resp.text
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

    async def test_og_title_for_nested_directory_post(self, client: AsyncClient) -> None:
        resp = await client.get("/post/2026/recap")
        assert resp.status_code == 200
        assert 'og:title" content="Nested Recap"' in resp.text


class TestPostSeoMetaTags:
    """New SEO meta tags on post pages."""

    async def test_meta_description_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert '<meta name="description"' in resp.text

    async def test_canonical_link_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert '<link rel="canonical"' in resp.text
        assert "/post/hello" in resp.text

    async def test_json_ld_blogposting(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert "application/ld+json" in resp.text
        assert '"BlogPosting"' in resp.text
        assert '"Hello World"' in resp.text

    async def test_rendered_body_inside_root(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert "post body with some content" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert "__initial_data__" in resp.text
        assert '"rendered_html"' not in resp.text

    async def test_rendered_body_has_data_content_marker(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert "data-content" in resp.text

    async def test_rendered_body_uses_css_classes_instead_of_inline_styles(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/post/hello")
        root_html = _extract_root_fragment(resp.text)
        assert 'class="server-shell"' in root_html
        assert 'class="server-meta"' in root_html
        assert 'style="' not in root_html

    async def test_rendered_body_strips_unsafe_markup(self, client: AsyncClient) -> None:
        resp = await client.get("/post/unsafe")
        assert resp.status_code == 200
        root_html = _extract_root_fragment(resp.text).lower()
        assert "<script>alert" not in root_html
        assert 'href="javascript:' not in root_html
        assert "safe intro." in root_html
        assert "safe outro." in root_html

    async def test_draft_has_no_rendered_body(self, client: AsyncClient) -> None:
        resp = await client.get("/post/my-draft")
        assert "Draft content" not in resp.text

    async def test_missing_post_has_no_seo(self, client: AsyncClient) -> None:
        resp = await client.get("/post/nonexistent")
        assert '<meta name="description"' not in resp.text
        assert "application/ld+json" not in resp.text
