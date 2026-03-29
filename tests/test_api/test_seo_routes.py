"""Integration tests for SEO-enriched route handlers."""

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
def seo_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: [python]\n---\n"
        "Hello body content for excerpt.\n"
    )

    post2 = posts_dir / "second"
    post2.mkdir()
    (post2 / "index.md").write_text(
        "---\ntitle: Second Post\ncreated_at: 2026-03-27 12:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "Second post body.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Secret Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\n"
        "Draft content.\n"
    )

    labels_toml = tmp_content_dir / "labels.toml"
    labels_toml.write_text('[labels.python]\nnames = ["Python"]\n')

    (tmp_content_dir / "about.md").write_text("# About\n\nThis is the about page content.\n")
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ndescription = "A test blog"\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        '<!DOCTYPE html><html><head><title>Blog</title></head>'
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
async def client(seo_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(seo_settings) as ac:
        yield ac


class TestHomepageSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_is_site_name(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "<title>Test Blog</title>" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '<meta name="description" content="A test blog">' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert 'og:type" content="website"' in resp.text

    async def test_json_ld_website(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '"WebSite"' in resp.text
        assert '"Test Blog"' in resp.text

    async def test_canonical_url(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '<link rel="canonical"' in resp.text

    async def test_rendered_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "/post/hello" in resp.text
        assert "Hello World" in resp.text
        assert "/post/second" in resp.text

    async def test_draft_not_in_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "Secret Draft" not in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "__initial_data__" in resp.text


class TestPageSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_includes_page_name(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "<title>About</title>" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert '<meta name="description"' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert 'og:type" content="website"' in resp.text

    async def test_json_ld_webpage(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert '"WebPage"' in resp.text
        assert '"About"' in resp.text

    async def test_rendered_body_present(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "about page content" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "__initial_data__" in resp.text

    async def test_unknown_page_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/page/nonexistent")
        assert resp.status_code == 200
        assert "og:title" not in resp.text

    async def test_builtin_page_without_file(self, client: AsyncClient) -> None:
        resp = await client.get("/page/timeline")
        assert resp.status_code == 200
        assert "<title>" in resp.text


class TestLabelsIndexSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert "Labels" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert '<meta name="description"' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert 'og:type" content="website"' in resp.text

    async def test_no_preload_data(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert "__initial_data__" not in resp.text


class TestLabelDetailSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_includes_label(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "Python" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert '<meta name="description"' in resp.text

    async def test_rendered_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "/post/hello" in resp.text
        assert "Hello World" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "__initial_data__" in resp.text

    async def test_unknown_label_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/nonexistent")
        assert resp.status_code == 200
        assert "og:title" not in resp.text


class TestSearchSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert "Search" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert '<meta name="description"' in resp.text

    async def test_no_preload_data(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert "__initial_data__" not in resp.text
