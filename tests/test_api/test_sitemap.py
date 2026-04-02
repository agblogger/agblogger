"""Integration tests for the sitemap.xml endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport
from sqlalchemy.exc import SQLAlchemyError

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

pytestmark = pytest.mark.slow


@pytest.fixture
def sitemap_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: [python]\n---\nBody.\n"
    )

    nested_parent = posts_dir / "2026"
    nested_parent.mkdir()
    nested = nested_parent / "recap"
    nested.mkdir()
    (nested / "index.md").write_text(
        "---\ntitle: 2026 Recap\ncreated_at: 2026-03-27 12:00:00+00\n"
        "author: admin\nlabels: []\n---\nNested body.\n"
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

    async def test_preserves_nested_slug_segments(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/post/2026/recap" in resp.text

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


class TestSitemapXmlEscaping:
    """Verify that XML-special characters in slugs/IDs are escaped in sitemap output."""

    @pytest.fixture
    def xml_escape_settings(self, tmp_path: Path) -> Settings:
        content_dir = tmp_path / "content"
        posts_dir = content_dir / "posts"
        posts_dir.mkdir(parents=True)

        # Post with an XML-special character in its slug (directory name)
        ampersand_post = posts_dir / "q&a"
        ampersand_post.mkdir()
        (ampersand_post / "index.md").write_text(
            "---\ntitle: Q&A Post\ncreated_at: 2026-01-05 12:00:00+00\n"
            "author: admin\nlabels: []\n---\nBody.\n"
        )

        labels_toml = content_dir / "labels.toml"
        labels_toml.write_text("[labels]\n")

        index_toml = content_dir / "index.toml"
        index_toml.write_text(
            '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
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
            content_dir=content_dir,
            frontend_dir=frontend_dir,
            admin_username="admin",
            admin_password="admin123",
        )

    @pytest.fixture
    async def xml_escape_client(self, xml_escape_settings: Settings) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(xml_escape_settings) as ac:
            yield ac

    async def test_ampersand_in_slug_is_escaped(self, xml_escape_client: AsyncClient) -> None:
        """Raw & in post slug must be escaped as &amp; in sitemap XML."""
        resp = await xml_escape_client.get("/sitemap.xml")
        assert resp.status_code == 200
        # The post URL must appear with &amp; escaping, not a raw &
        assert "/post/q&amp;a" in resp.text
        # A raw unescaped & followed by 'a' in a URL context must not appear
        # (the only & that should exist is part of &amp;)
        assert "<loc>http://test/post/q&a</loc>" not in resp.text


class TestSitemapDatabaseError:
    async def test_db_error_returns_503_with_retry_after(self, client: AsyncClient) -> None:
        """Sitemap route must return 503 with Retry-After when the database is unavailable."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.side_effect = SQLAlchemyError("DB down")

        mock_session = AsyncMock()
        mock_session.execute.side_effect = SQLAlchemyError("DB down")

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        transport = client._transport
        assert isinstance(transport, ASGITransport)
        state = getattr(transport.app, "state", None)
        assert state is not None
        state.session_factory = mock_session_factory

        resp = await client.get("/sitemap.xml")
        assert resp.status_code == 503
        assert "Retry-After" in resp.headers
