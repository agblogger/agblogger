"""Integration tests for analytics hit recording in post and page endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings with a sample post and page for hit recording tests."""
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n# Hello World\n\nTest content.\n"
    )
    # Add a file-backed page to the site config
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '\n[[pages]]\nid = "nofile"\ntitle = "No File Page"\n'
    )
    (tmp_content_dir / "about.md").write_text("# About\n\nAbout page.\n")
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!doctype html><html><head><title>AgBlogger</title></head>"
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
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _get_admin_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestPostHitRecording:
    """Verify hit recording is triggered (or skipped) on GET /api/posts/{slug}."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_fires_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/hello")
            assert resp.status_code == 200
            # Allow the background task to run
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/post/hello"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_authenticated_request_skips_hit(self, client: AsyncClient) -> None:
        import asyncio

        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get(
                "/api/posts/hello",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            await asyncio.sleep(0)
        # record_hit is still called but the service itself skips authenticated users.
        # We verify the user argument is NOT None (so the service can make that decision).
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["user"] is not None

    @pytest.mark.asyncio
    async def test_hit_recorded_with_correct_path(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/posts/hello/index.md")
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/post/hello"

    @pytest.mark.asyncio
    async def test_nonexistent_post_does_not_fire_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/posts/does-not-exist")
            assert resp.status_code == 404
            await asyncio.sleep(0)
        mock_record.assert_not_called()


class TestPageHitRecording:
    """Verify hit recording is triggered on GET /api/pages/{page_id}."""

    @pytest.mark.asyncio
    async def test_unauthenticated_page_request_fires_hit(self, client: AsyncClient) -> None:
        """Request a file-backed page (about) — cache row seeded by rebuild_cache."""
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/pages/about")
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/page/about"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_authenticated_page_request_passes_user_to_record_hit(
        self, client: AsyncClient
    ) -> None:
        """Request a file-backed page (about) with auth — cache row seeded by rebuild_cache."""
        import asyncio

        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get(
                "/api/pages/about",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            await asyncio.sleep(0)
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["user"] is not None

    @pytest.mark.asyncio
    async def test_fileless_page_returns_404(self, client: AsyncClient) -> None:
        """Pages without backing files (timeline, labels) now return 404."""
        resp = await client.get("/api/pages/timeline")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_custom_fileless_page_returns_empty_html(self, client: AsyncClient) -> None:
        resp = await client.get("/api/pages/nofile")

        assert resp.status_code == 200
        assert resp.json() == {
            "id": "nofile",
            "title": "No File Page",
            "rendered_html": "",
        }

    @pytest.mark.asyncio
    async def test_nonexistent_page_does_not_fire_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/api/pages/does-not-exist")
            assert resp.status_code == 404
            await asyncio.sleep(0)
        mock_record.assert_not_called()


class TestFrontendSeoRouteHitRecording:
    """Verify hit recording is triggered on server-rendered frontend routes."""

    @pytest.mark.asyncio
    async def test_unauthenticated_post_route_fires_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/post/hello")
            assert resp.status_code == 200
            await asyncio.sleep(0)

        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/post/hello"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_unauthenticated_page_route_fires_hit(self, client: AsyncClient) -> None:
        import asyncio

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get("/page/about")
            assert resp.status_code == 200
            await asyncio.sleep(0)

        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["path"] == "/page/about"
        assert call_kwargs["user"] is None

    @pytest.mark.asyncio
    async def test_authenticated_post_route_passes_user_to_record_hit(
        self, client: AsyncClient
    ) -> None:
        import asyncio

        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            resp = await client.get(
                "/post/hello",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            await asyncio.sleep(0)

        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["user"] is not None


class TestPostHitSessionFactoryFailure:
    """Verify that session_factory failure in _do_hit does not crash the server."""

    @pytest.mark.asyncio
    async def test_session_factory_raises_logs_warning_and_does_not_propagate(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_do_hit exception is caught and logged; the background task does not propagate it."""
        import asyncio
        import logging
        from unittest.mock import MagicMock

        from backend.api.posts import _fire_post_hit

        # session_factory() raises RuntimeError to simulate pool exhaustion
        failing_factory = MagicMock(side_effect=RuntimeError("pool exhausted"))

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"user-agent": "test-agent"}

        with caplog.at_level(logging.WARNING, logger="backend.services.analytics_service"):
            _fire_post_hit(mock_request, failing_factory, "posts/hello/index.md", None)
            # Allow background task to run and complete
            await asyncio.sleep(0.01)

        assert any("Background analytics hit failed" in record.message for record in caplog.records)


class TestPageHitSessionFactoryFailure:
    """Verify that session_factory failure in _do_hit does not crash the server."""

    @pytest.mark.asyncio
    async def test_session_factory_raises_logs_warning_and_does_not_propagate(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_do_hit exception is caught and logged; the background task does not propagate it."""
        import asyncio
        import logging

        # "about" page cache row seeded by rebuild_cache during app startup.
        # Use record_hit raising to trigger exception inside the _do_hit body,
        # which exercises the same try/except block as a session_factory failure.
        with (
            caplog.at_level(logging.WARNING, logger="backend.services.analytics_service"),
            patch(
                "backend.services.analytics_service.record_hit",
                new=AsyncMock(side_effect=RuntimeError("pool exhausted")),
            ),
        ):
            resp = await client.get("/api/pages/about")
            assert resp.status_code == 200
            await asyncio.sleep(0.01)

        assert any("Background analytics hit failed" in record.message for record in caplog.records)


class TestPostHitRequestClientNone:
    """Issue 11: Verify _fire_post_hit handles request.client = None gracefully."""

    @pytest.mark.asyncio
    async def test_fire_post_hit_with_request_client_none(self) -> None:
        """When request.client is None, client_ip should be 'unknown'."""
        import asyncio
        from unittest.mock import MagicMock

        from backend.api.posts import _fire_post_hit

        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers = {"user-agent": "test-agent"}

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            mock_session = AsyncMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            _fire_post_hit(mock_request, mock_session_factory, "posts/hello/index.md", None)
            await asyncio.sleep(0.01)

        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["client_ip"] == "unknown"


class TestPageHitRequestClientNone:
    """Issue 11: Verify fire_background_hit handles request.client = None gracefully."""

    @pytest.mark.asyncio
    async def test_fire_background_hit_with_request_client_none(self) -> None:
        """When request.client is None, fire_background_hit passes 'unknown' as IP."""
        import asyncio
        from unittest.mock import MagicMock

        from backend.services.analytics_service import fire_background_hit

        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers = {"user-agent": "test-agent"}

        with patch(
            "backend.services.analytics_service.record_hit",
            new=AsyncMock(),
        ) as mock_record:
            mock_session = AsyncMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            fire_background_hit(mock_request, mock_session_factory, "/page/timeline", None)
            await asyncio.sleep(0.01)

        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["client_ip"] == "unknown"


class TestFirePostHitNonCanonicalPath:
    """Verify _fire_post_hit skips task creation for non-canonical file paths."""

    @pytest.mark.asyncio
    async def test_non_canonical_file_path_skips_hit(self) -> None:
        from unittest.mock import MagicMock

        from backend.api.posts import _fire_post_hit

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"user-agent": "test-agent"}

        mock_session_factory = MagicMock()

        # A path starting with "posts/" but not matching "posts/<slug>/index.md"
        # causes file_path_to_slug to raise ValueError (e.g. flat .md file)
        with patch("backend.api.posts.fire_background_hit") as mock_fire:
            _fire_post_hit(mock_request, mock_session_factory, "posts/my-post.md", None)
            mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_canonical_file_path_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_fire_post_hit logs a warning when file_path_to_slug raises ValueError."""
        import logging
        from unittest.mock import MagicMock

        from backend.api.posts import _fire_post_hit

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"user-agent": "test-agent"}

        mock_session_factory = MagicMock()

        with caplog.at_level(logging.WARNING, logger="backend.api.posts"):
            _fire_post_hit(mock_request, mock_session_factory, "posts/my-post.md", None)

        assert any("posts/my-post.md" in r.message for r in caplog.records)
