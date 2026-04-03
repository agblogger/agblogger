"""Tests for the RSS feed endpoint (/feed.xml).

Covers XML-special character escaping in post titles and excerpts so that
malformed XML is never served to feed readers.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def feed_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with published posts whose titles contain XML-special characters."""
    posts_dir = tmp_content_dir / "posts"

    # Post with & in title
    amp_post = posts_dir / "post-with-amp"
    amp_post.mkdir()
    (amp_post / "index.md").write_text(
        '---\ntitle: "Cats & Dogs"\ncreated_at: 2026-03-01 10:00:00+00\n'
        "author: admin\nlabels: []\n---\n"
        "A post about cats and dogs.\n"
    )

    # Post with < and > in title
    ltgt_post = posts_dir / "post-with-ltgt"
    ltgt_post.mkdir()
    (ltgt_post / "index.md").write_text(
        '---\ntitle: "a < b > c"\ncreated_at: 2026-03-02 10:00:00+00\n'
        "author: admin\nlabels: []\n---\n"
        "A post with angle brackets.\n"
    )

    # Post with & and < in the excerpt (body)
    special_excerpt_post = posts_dir / "post-with-special-excerpt"
    special_excerpt_post.mkdir()
    (special_excerpt_post / "index.md").write_text(
        '---\ntitle: "Plain Title"\ncreated_at: 2026-03-03 10:00:00+00\n'
        "author: admin\nlabels: []\n---\n"
        "An excerpt with both & ampersand and <angle> brackets.\n"
    )

    # Post with > and " in title
    gt_quot_post = posts_dir / "post-with-gt-quot"
    gt_quot_post.mkdir()
    (gt_quot_post / "index.md").write_text(
        "---\ntitle: 'Say \"hello\" > world'\ncreated_at: 2026-03-04 10:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "A post with greater-than and double-quotes in title.\n"
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
async def feed_client(feed_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Test HTTP client for feed escaping tests."""
    async with create_test_client(feed_settings) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedTitleEscaping:
    """RSS feed properly XML-escapes special characters in post titles."""

    async def test_ampersand_in_title_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # Raw & must not appear as a literal inside an XML element value
        assert "<title>Cats & Dogs</title>" not in resp.text
        # Properly escaped form must appear
        assert "&amp;" in resp.text

    async def test_less_than_in_title_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # Raw < in a title would break the XML
        assert "<title>a < b > c</title>" not in resp.text
        assert "&lt;" in resp.text

    async def test_greater_than_in_title_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # html.escape encodes > as &gt;
        assert "&gt;" in resp.text

    async def test_double_quote_in_title_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # Quotes in XML character data are valid unescaped, but the title text must survive intact.
        assert (
            'Say "hello" &gt; world' in resp.text or "Say &quot;hello&quot; &gt; world" in resp.text
        )

    async def test_feed_is_valid_xml_with_special_title_chars(
        self, feed_client: AsyncClient
    ) -> None:
        """The feed response must contain a well-formed RSS envelope."""
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # Well-formed RSS must have a root <rss> element and a <channel>
        assert resp.text.startswith("<?xml")
        assert "<rss" in resp.text
        assert "<channel>" in resp.text
        assert "</channel>" in resp.text
        assert "</rss>" in resp.text

    async def test_content_type_is_rss_xml(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        assert "xml" in resp.headers["content-type"]


class TestFeedExcerptEscaping:
    """RSS feed properly XML-escapes special characters in post excerpts/descriptions."""

    async def test_ampersand_in_excerpt_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # The post body "...both & ampersand..." — after strip_html_tags the raw &
        # must not appear unescaped in <description>; &amp; must be present
        assert "&amp;" in resp.text

    async def test_less_than_in_excerpt_is_escaped(self, feed_client: AsyncClient) -> None:
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        # Excerpt body contains "<angle>" — after strip_html_tags the angle brackets
        # become plain text and must be escaped; &lt; must appear in the feed
        assert "&lt;" in resp.text

    async def test_feed_with_special_excerpt_has_well_formed_envelope(
        self, feed_client: AsyncClient
    ) -> None:
        """Feed with special chars in excerpt must still have a well-formed RSS envelope."""
        resp = await feed_client.get("/feed.xml")
        assert resp.status_code == 200
        assert resp.text.startswith("<?xml")
        assert "<rss" in resp.text
        assert "<channel>" in resp.text
        assert "</channel>" in resp.text
        assert "</rss>" in resp.text
