"""Integration tests for the RSS feed endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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


class TestFeedNestedSlugAndUtcNormalization:
    @pytest.fixture
    def nested_offset_feed_settings(self, tmp_path: Path) -> Settings:
        content_dir = tmp_path / "content"
        posts_dir = content_dir / "posts"
        posts_dir.mkdir(parents=True)

        nested_parent = posts_dir / "2026"
        nested_parent.mkdir()
        nested = nested_parent / "recap"
        nested.mkdir()
        (nested / "index.md").write_text(
            "---\ntitle: 2026 Recap\ncreated_at: 2026-03-28 12:00:00+02:00\n"
            "author: admin\nlabels: []\n---\nBody.\n"
        )

        index_toml = content_dir / "index.toml"
        index_toml.write_text(
            '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )

        labels_toml = content_dir / "labels.toml"
        labels_toml.write_text("[labels]\n")

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
    async def nested_offset_feed_client(
        self, nested_offset_feed_settings: Settings
    ) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(nested_offset_feed_settings) as ac:
            yield ac

    async def test_preserves_nested_slug_segments(
        self, nested_offset_feed_client: AsyncClient
    ) -> None:
        resp = await nested_offset_feed_client.get("/feed.xml")
        assert resp.status_code == 200
        assert "/post/2026/recap" in resp.text

    async def test_normalizes_pubdate_to_gmt(self, nested_offset_feed_client: AsyncClient) -> None:
        aware_post = SimpleNamespace(
            file_path="posts/2026/recap/index.md",
            title="2026 Recap",
            rendered_excerpt="<p>Body.</p>",
            created_at=datetime(2026, 3, 28, 12, 0, tzinfo=timezone(timedelta(hours=2))),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [aware_post]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        transport = nested_offset_feed_client._transport
        assert isinstance(transport, ASGITransport)
        state = getattr(transport.app, "state", None)
        assert state is not None
        state.session_factory = mock_session_factory

        resp = await nested_offset_feed_client.get("/feed.xml")
        assert resp.status_code == 200
        assert "<pubDate>Sat, 28 Mar 2026 10:00:00 GMT</pubDate>" in resp.text


class TestFeedXmlEscaping:
    """Verify that XML-special characters in post slugs are escaped in feed output."""

    @pytest.fixture
    def xml_escape_feed_settings(self, tmp_path: Path) -> Settings:
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

        index_toml = content_dir / "index.toml"
        index_toml.write_text(
            '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )

        labels_toml = content_dir / "labels.toml"
        labels_toml.write_text("[labels]\n")

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
    async def xml_escape_feed_client(
        self, xml_escape_feed_settings: Settings
    ) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(xml_escape_feed_settings) as ac:
            yield ac

    async def test_ampersand_in_slug_is_escaped_in_link(
        self, xml_escape_feed_client: AsyncClient
    ) -> None:
        """Raw & in post slug must be escaped as &amp; in feed XML link/guid elements."""
        resp = await xml_escape_feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # The raw unescaped & must not appear in <link> or <guid> URL elements
        assert "/post/q&a</link>" not in resp.text
        assert '/post/q&a"' not in resp.text
        assert "/post/q&amp;a" in resp.text


class TestFeedDatabaseError:
    async def test_db_error_returns_503_with_retry_after(self, client: AsyncClient) -> None:
        """Feed route must return 503 with Retry-After when the database is unavailable."""
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

        resp = await client.get("/feed.xml")
        assert resp.status_code == 503
        assert "Retry-After" in resp.headers
