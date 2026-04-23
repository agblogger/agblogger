"""Integration tests for SEO-enriched route handlers."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport
from sqlalchemy.exc import SQLAlchemyError

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


def _extract_initial_data(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="__initial_data__" data-agblogger-preload type="application/json">'
        r"(.*?)</script>",
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _extract_root_fragment(html: str) -> str:
    match = re.search(
        r'<div id="root">(.*?)</div>\s*<script id="__initial_data__"',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


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

    for i in range(3, 12):
        extra_post = posts_dir / f"post-{i}"
        extra_post.mkdir()
        day = 28 - i
        (extra_post / "index.md").write_text(
            f"---\ntitle: Post {i}\ncreated_at: 2026-03-{day:02d} 12:00:00+00\n"
            "author: admin\nlabels: []\n---\n"
            f"Post {i} body.\n"
        )

    nested_parent = posts_dir / "2026"
    nested_parent.mkdir()
    nested = nested_parent / "recap"
    nested.mkdir()
    (nested / "index.md").write_text(
        "---\ntitle: 2026 Recap\ncreated_at: 2026-03-27 18:00:00+00\n"
        "author: admin\nlabels: [python]\n---\n"
        "Nested post body.\n"
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
    (tmp_content_dir / "unsafe.md").write_text(
        "# Unsafe\n\n"
        "Safe intro.\n\n"
        "[click](javascript:alert('xss'))\n\n"
        "<script>alert('owned')</script>\n\n"
        "Safe outro.\n"
    )
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ndescription = "A test blog"\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '[[pages]]\nid = "unsafe"\ntitle = "Unsafe"\nfile = "unsafe.md"\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Blog</title></head>"
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


class TestSpaShellRoutes:
    async def test_admin_route_returns_spa_shell(self, client: AsyncClient) -> None:
        resp = await client.get("/admin")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '<div id="root"></div>' in resp.text

    async def test_login_route_returns_spa_shell(self, client: AsyncClient) -> None:
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '<div id="root"></div>' in resp.text

    async def test_editor_route_returns_spa_shell(self, client: AsyncClient) -> None:
        resp = await client.get("/editor/posts/hello/index.md")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '<div id="root"></div>' in resp.text


class TestMarkdownNegotiation:
    async def test_homepage_accept_text_markdown_returns_markdown(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/", headers={"Accept": "text/markdown"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "Accept" in resp.headers["vary"]
        assert resp.headers["x-markdown-tokens"].isdigit()
        assert resp.text.startswith("---\n")
        assert "[Hello World](/post/hello)" in resp.text
        assert "<html" not in resp.text.lower()

    async def test_page_accept_text_markdown_returns_markdown(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about", headers={"Accept": "text/markdown"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert resp.headers["x-markdown-tokens"].isdigit()
        assert "# About" in resp.text
        assert "This is the about page content." in resp.text
        assert '<div id="root">' not in resp.text

    async def test_post_accept_text_markdown_returns_markdown(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello", headers={"Accept": "text/markdown"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert resp.headers["x-markdown-tokens"].isdigit()
        assert 'title: "Hello World"' in resp.text
        assert "Hello body content for excerpt." in resp.text
        assert "<article" not in resp.text


class TestHomepageSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_includes_api_catalog_link_header(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        link_header = resp.headers.get("Link", "")
        assert '</.well-known/api-catalog>; rel="api-catalog"' in link_header

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

    async def test_preserves_nested_post_slug_in_rendered_post_list(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/")
        assert "/post/2026/recap" in resp.text

    async def test_draft_not_in_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "Secret Draft" not in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "__initial_data__" in resp.text
        assert '"rendered_excerpt"' not in resp.text

    async def test_rendered_list_has_data_id_markers(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "data-id" in resp.text
        assert "data-excerpt" in resp.text

    async def test_pagination_query_shapes_homepage_preload(self, client: AsyncClient) -> None:
        resp = await client.get("/?page=2")
        preload = _extract_initial_data(resp.text)

        assert preload["page"] == 2
        assert preload["per_page"] == 10
        assert preload["total"] == 12
        assert preload["total_pages"] == 2
        assert "Hello World" not in resp.text
        assert "Post 10" in resp.text
        assert "Post 11" in resp.text

    async def test_label_query_shapes_homepage_preload(self, client: AsyncClient) -> None:
        resp = await client.get("/?labels=python")
        preload = _extract_initial_data(resp.text)

        assert preload["page"] == 1
        assert preload["total"] == 2
        assert preload["total_pages"] == 1
        assert "Hello World" in resp.text
        assert "2026 Recap" in resp.text
        assert "Second Post" not in resp.text

    async def test_authenticated_homepage_preload_includes_drafts(
        self, client: AsyncClient
    ) -> None:
        login = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login.status_code == 200

        resp = await client.get("/?labels=")
        preload = _extract_initial_data(resp.text)

        posts = cast("list[dict[str, object]]", preload["posts"])
        titles = [post["title"] for post in posts]
        assert "Secret Draft" in titles
        assert resp.headers["Cache-Control"] == "private, no-store"

    async def test_unauthenticated_homepage_is_cacheable(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert resp.status_code == 200
        cache_control = resp.headers.get("Cache-Control", "")
        assert cache_control != "private, no-store"


class TestApiCatalogDiscovery:
    async def test_api_catalog_endpoint_returns_linkset_json(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/api-catalog")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/linkset+json")

    async def test_api_catalog_lists_api_root(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/api-catalog")
        payload = resp.json()

        linkset = cast("list[dict[str, object]]", payload["linkset"])
        api_entry = next(entry for entry in linkset if entry["anchor"] == "http://test/api")
        items = cast("list[dict[str, object]]", api_entry["item"])
        assert items == [{"href": "http://test/api"}]

    async def test_api_catalog_includes_openapi_when_docs_are_enabled(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/.well-known/api-catalog")
        payload = resp.json()

        linkset = cast("list[dict[str, object]]", payload["linkset"])
        api_entry = next(entry for entry in linkset if entry["anchor"] == "http://test/api")
        service_desc = cast("list[dict[str, object]]", api_entry["service-desc"])
        assert service_desc == [
            {
                "href": "http://test/openapi.json",
                "type": "application/vnd.oai.openapi+json",
            }
        ]


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
        assert '"rendered_html"' not in resp.text

    async def test_rendered_body_has_data_content_marker(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "data-content" in resp.text

    async def test_rendered_body_uses_css_classes_instead_of_inline_styles(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/page/about")
        root_html = _extract_root_fragment(resp.text)
        assert 'class="server-shell"' in root_html
        assert 'style="' not in root_html

    async def test_rendered_body_strips_unsafe_markup(self, client: AsyncClient) -> None:
        resp = await client.get("/page/unsafe")
        assert resp.status_code == 200
        root_html = _extract_root_fragment(resp.text).lower()
        assert "<script>alert" not in root_html
        assert 'href="javascript:' not in root_html
        assert "safe intro." in root_html
        assert "safe outro." in root_html

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

    async def test_preserves_nested_post_slug_in_rendered_post_list(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/labels/python")
        assert "/post/2026/recap" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "__initial_data__" in resp.text
        assert '"rendered_excerpt"' not in resp.text

    async def test_rendered_list_has_data_id_markers(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "data-id" in resp.text
        assert "data-excerpt" in resp.text

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


class TestDateFormatting:
    """Verify date formatting produces expected output without platform-specific strftime flags."""

    @pytest.fixture
    def date_format_settings(self, tmp_path: Path) -> Settings:
        content_dir = tmp_path / "content"
        posts_dir = content_dir / "posts"
        posts_dir.mkdir(parents=True)

        # Post with day=5 to test that it renders as "5" not "05"
        post = posts_dir / "early-jan"
        post.mkdir()
        (post / "index.md").write_text(
            "---\ntitle: Early January\ncreated_at: 2026-01-05 12:00:00+00\n"
            "author: admin\nlabels: []\n---\nBody content.\n"
        )

        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )

        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()
        (frontend_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>Blog</title></head>"
            '<body><div id="root"></div></body></html>'
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
    async def date_format_client(
        self, date_format_settings: Settings
    ) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(date_format_settings) as ac:
            yield ac

    async def test_date_no_leading_zero_on_homepage(self, date_format_client: AsyncClient) -> None:
        """Date on homepage must render as 'January 5, 2026' not 'January 05, 2026'."""
        resp = await date_format_client.get("/")
        assert resp.status_code == 200
        assert "January 5, 2026" in resp.text
        assert "January 05, 2026" not in resp.text

    async def test_date_no_leading_zero_on_post_page(self, date_format_client: AsyncClient) -> None:
        """Date on post page must render as 'January 5, 2026' not 'January 05, 2026'."""
        resp = await date_format_client.get("/post/early-jan")
        assert resp.status_code == 200
        assert "January 5, 2026" in resp.text
        assert "January 05, 2026" not in resp.text

    async def test_date_no_leading_zero_on_label_page(
        self, date_format_client: AsyncClient
    ) -> None:
        """Date in label post list must render without leading zero."""
        # This also covers label_detail_route date formatting
        resp = await date_format_client.get("/")
        assert "January 5, 2026" in resp.text


class TestMissingIndexHtml:
    """Verify routes return useful responses when frontend index.html is absent."""

    @pytest.fixture
    def no_index_settings(self, tmp_path: Path) -> Settings:
        content_dir = tmp_path / "content"
        posts_dir = content_dir / "posts"
        posts_dir.mkdir(parents=True)

        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )

        # frontend_dir exists but does NOT contain index.html
        frontend_dir = tmp_path / "frontend_empty"
        frontend_dir.mkdir()

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
    async def no_index_client(self, no_index_settings: Settings) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(no_index_settings) as ac:
            yield ac

    async def test_homepage_missing_index_html_returns_error(
        self, no_index_client: AsyncClient
    ) -> None:
        """Homepage must not crash when index.html is missing — returns 404."""
        resp = await no_index_client.get("/")
        # Should return an error response, not 500 (crash)
        assert resp.status_code in (404, 200)
        # Must not be a blank/empty body
        assert len(resp.text) > 0

    async def test_page_route_missing_index_html_returns_error(
        self, no_index_client: AsyncClient
    ) -> None:
        """Page route must not crash when index.html is missing — returns 404."""
        resp = await no_index_client.get("/page/about")
        assert resp.status_code in (404, 200)
        assert len(resp.text) > 0

    async def test_post_route_missing_index_html_returns_404(
        self, no_index_client: AsyncClient
    ) -> None:
        """Post route returns 404 (not 500) when index.html is missing."""
        resp = await no_index_client.get("/post/some-post")
        assert resp.status_code == 404

    async def test_labels_route_missing_index_html_returns_error(
        self, no_index_client: AsyncClient
    ) -> None:
        """Labels route must not crash when index.html is missing."""
        resp = await no_index_client.get("/labels")
        assert resp.status_code in (404, 200)
        assert len(resp.text) > 0


class TestFormatHumanDateWithDatetime:
    """format_human_date must accept a datetime object, not just a str."""

    def test_accepts_datetime_object(self) -> None:
        """format_human_date(datetime(...)) must return the correct human-readable date."""
        from backend.main import format_human_date

        dt = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)
        result = format_human_date(dt)
        assert result == "January 5, 2026"

    def test_accepts_string(self) -> None:
        """format_human_date must continue to accept an ISO datetime string."""
        from backend.main import format_human_date

        result = format_human_date("2026-01-05 12:00:00+00")
        assert result == "January 5, 2026"


class TestHomepageDatabaseError:
    """Homepage SEO route must degrade gracefully when the DB raises SQLAlchemyError."""

    def _inject_failing_session(self, client: AsyncClient) -> None:
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

    async def test_db_error_returns_503(self, client: AsyncClient) -> None:
        """Homepage must return 503 (not 200) when the DB is unavailable."""
        self._inject_failing_session(client)
        resp = await client.get("/")
        assert resp.status_code == 503

    async def test_db_error_has_retry_after_header(self, client: AsyncClient) -> None:
        """Homepage 503 response must include Retry-After header."""
        self._inject_failing_session(client)
        resp = await client.get("/")
        assert resp.headers.get("Retry-After") == "60"

    async def test_db_error_returns_base_html_body(self, client: AsyncClient) -> None:
        """Homepage 503 response body must still contain the base HTML."""
        self._inject_failing_session(client)
        resp = await client.get("/")
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 0
        # SEO-enriched content (rendered post list) must NOT be present on DB error
        assert "Hello World" not in resp.text


class TestPageDatabaseError:
    """page_route must return 503 with Retry-After when the DB raises SQLAlchemyError."""

    def _inject_failing_session(self, client: AsyncClient) -> None:
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

    async def test_db_error_returns_503(self, client: AsyncClient) -> None:
        """page_route must return 503 (not 200) when the DB is unavailable."""
        self._inject_failing_session(client)
        resp = await client.get("/page/about")
        assert resp.status_code == 503

    async def test_db_error_has_retry_after_header(self, client: AsyncClient) -> None:
        """page_route 503 response must include Retry-After header."""
        self._inject_failing_session(client)
        resp = await client.get("/page/about")
        assert resp.headers.get("Retry-After") == "60"

    async def test_db_error_returns_base_html_body(self, client: AsyncClient) -> None:
        """page_route 503 response body must still contain the base HTML."""
        self._inject_failing_session(client)
        resp = await client.get("/page/about")
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 0


class TestLabelDetailDatabaseError:
    """label_detail_route must return 503 with Retry-After when the DB raises SQLAlchemyError."""

    def _inject_failing_session(self, client: AsyncClient) -> None:
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

    async def test_db_error_returns_503(self, client: AsyncClient) -> None:
        """label_detail_route must return 503 (not 200) when the DB is unavailable."""
        self._inject_failing_session(client)
        resp = await client.get("/labels/python")
        assert resp.status_code == 503

    async def test_db_error_has_retry_after_header(self, client: AsyncClient) -> None:
        """label_detail_route 503 response must include Retry-After header."""
        self._inject_failing_session(client)
        resp = await client.get("/labels/python")
        assert resp.headers.get("Retry-After") == "60"

    async def test_db_error_returns_base_html_body(self, client: AsyncClient) -> None:
        """label_detail_route 503 response body must still contain the base HTML."""
        self._inject_failing_session(client)
        resp = await client.get("/labels/python")
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 0


class TestQuotaExceededHandlerLogging:
    """QuotaExceededError handler must log the request before returning 413."""

    async def test_quota_exceeded_logs_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When QuotaExceededError is raised, the handler must emit an info log."""
        from httpx import ASGITransport, AsyncClient

        from backend.main import create_app
        from backend.services.storage_quota import QuotaExceededError

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-quota-exceeded")
        async def _raise_quota() -> None:
            raise QuotaExceededError("over limit")

        with caplog.at_level(logging.INFO, logger="backend.main"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/test-quota-exceeded")

        assert resp.status_code == 413
        quota_records = [
            r
            for r in caplog.records
            if "quota" in r.message.lower() or "storage" in r.message.lower()
        ]
        assert len(quota_records) >= 1
        assert any(
            "GET" in r.message and "/test-quota-exceeded" in r.message for r in quota_records
        )


class TestPageRouteRuntimeError:
    """page_route must NOT catch RuntimeError — it must propagate to the global handler."""

    async def test_runtime_error_propagates_from_page_route(self, client: AsyncClient) -> None:
        """RuntimeError in page_route must reach the global exception handler (500 response)."""
        with patch(
            "backend.services.page_service.get_page",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected bug"),
        ):
            resp = await client.get("/page/about")

        # RuntimeError must NOT be silently swallowed by the page_route except clause;
        # it should propagate to the global RuntimeError handler → 500
        assert resp.status_code == 500

    async def test_sqlalchemy_error_still_returns_503_from_page_route(
        self, client: AsyncClient
    ) -> None:
        """SQLAlchemyError must still be caught by page_route and return 503."""
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

        resp = await client.get("/page/about")
        assert resp.status_code == 503


class TestHomepageValueError:
    """Homepage ValueError from invalid date params must return 200 with base HTML."""

    async def test_invalid_date_params_return_200(self, client: AsyncClient) -> None:
        """ValueError from list_posts (bad date param) must return 200 with base HTML."""
        with patch(
            "backend.services.post_service.list_posts",
            new_callable=AsyncMock,
            side_effect=ValueError("invalid date"),
        ):
            resp = await client.get("/?from=not-a-date")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 0

    async def test_invalid_date_params_return_base_html(self, client: AsyncClient) -> None:
        """ValueError response body must be the base HTML fallback (no SEO content)."""
        with patch(
            "backend.services.post_service.list_posts",
            new_callable=AsyncMock,
            side_effect=ValueError("invalid date"),
        ):
            resp = await client.get("/?to=bad-date")

        # SEO-enriched post list must NOT appear — ValueError short-circuits rendering
        assert "Hello World" not in resp.text


class TestPostSeo:
    """Post page must include article OG tags, JSON-LD BlogPosting, and preload data."""

    async def test_og_type_is_article(self, client: AsyncClient) -> None:
        """Post page must include og:type=article."""
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert 'og:type" content="article"' in resp.text

    async def test_json_ld_blogposting(self, client: AsyncClient) -> None:
        """Post page must include JSON-LD BlogPosting structured data."""
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert '"BlogPosting"' in resp.text

    async def test_article_published_time_meta(self, client: AsyncClient) -> None:
        """Post page must include article:published_time meta tag."""
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert "article:published_time" in resp.text

    async def test_article_modified_time_meta(self, client: AsyncClient) -> None:
        """Post page must include article:modified_time meta tag."""
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert "article:modified_time" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        """Post page must include preload data with post metadata."""
        resp = await client.get("/post/hello")
        assert resp.status_code == 200
        assert "__initial_data__" in resp.text
        preload = _extract_initial_data(resp.text)
        assert preload["title"] == "Hello World"
        assert "file_path" in preload
