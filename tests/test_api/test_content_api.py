"""Tests for the content file serving endpoint."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for the content API tests."""
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
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(app_settings) as ac:
        yield ac


class TestContentServing:
    """Tests for GET /api/content/{file_path}."""

    @pytest.mark.asyncio
    async def test_serve_image_from_posts(self, client: AsyncClient, tmp_content_dir: Path) -> None:
        """Serving an image from posts/ returns 200 with correct content-type."""
        # Create a post directory with an image
        post_dir = tmp_content_dir / "posts" / "my-post"
        post_dir.mkdir(parents=True, exist_ok=True)
        # Write a minimal 1x1 PNG
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        (post_dir / "photo.png").write_bytes(png_bytes)

        resp = await client.get("/api/content/posts/my-post/photo.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == png_bytes

    @pytest.mark.asyncio
    async def test_serve_file_from_assets(self, client: AsyncClient, tmp_content_dir: Path) -> None:
        """Serving a file from assets/ returns 200."""
        assets_dir = tmp_content_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        (assets_dir / "style.css").write_text("body { color: red; }")

        resp = await client.get("/api/content/assets/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_404(self, client: AsyncClient) -> None:
        """Requesting a file that doesn't exist returns 404."""
        resp = await client.get("/api/content/posts/no-such-file.png")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_is_blocked(self, client: AsyncClient) -> None:
        """Path traversal attempts with .. return opaque 404.

        All rejection paths (traversal, disallowed prefix, resolved-outside-root)
        return 404 so the response is indistinguishable from a genuinely missing
        file regardless of encoding technique.
        """
        resp = await client.get("/api/content/posts/../index.toml")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_encoded_returns_404(self, client: AsyncClient) -> None:
        """Path traversal with encoded segments returns opaque 404."""
        resp = await client.get("/api/content/posts/..%2Findex.toml")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_disallowed_prefix_returns_404(self, client: AsyncClient) -> None:
        """Accessing files outside posts/ and assets/ returns opaque 404."""
        resp = await client.get("/api/content/index.toml")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_labels_toml_returns_404(self, client: AsyncClient) -> None:
        """Accessing labels.toml returns opaque 404."""
        resp = await client.get("/api/content/labels.toml")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client: AsyncClient, tmp_content_dir: Path) -> None:
        """Content endpoint does not require authentication."""
        post_dir = tmp_content_dir / "posts" / "public-post"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "readme.txt").write_text("hello")

        # No auth headers or cookies — should still succeed
        resp = await client.get("/api/content/posts/public-post/readme.txt")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_symlink_following(self, client: AsyncClient, tmp_content_dir: Path) -> None:
        """Symlinks within the content directory are followed."""
        # Create a real file
        post_dir = tmp_content_dir / "posts" / "original"
        post_dir.mkdir(parents=True, exist_ok=True)
        real_file = post_dir / "image.png"
        real_file.write_bytes(b"fake-png-data")

        # Create a symlink in another post directory pointing to the real file
        link_dir = tmp_content_dir / "posts" / "linked"
        link_dir.mkdir(parents=True, exist_ok=True)
        symlink = link_dir / "image.png"
        symlink.symlink_to(real_file)

        resp = await client.get("/api/content/posts/linked/image.png")
        assert resp.status_code == 200
        assert resp.content == b"fake-png-data"

    @pytest.mark.asyncio
    async def test_serve_pdf_from_posts(self, client: AsyncClient, tmp_content_dir: Path) -> None:
        """Potentially active document types are forced to download."""
        post_dir = tmp_content_dir / "posts" / "docs"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")

        resp = await client.get("/api/content/posts/docs/paper.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.headers["content-disposition"].startswith("attachment")
        assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"

    @pytest.mark.asyncio
    async def test_serve_html_asset_as_attachment(
        self, client: AsyncClient, tmp_content_dir: Path
    ) -> None:
        """HTML assets should never be rendered inline under the app origin."""
        post_dir = tmp_content_dir / "posts" / "unsafe"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "payload.html").write_text("<script>alert(1)</script>", encoding="utf-8")

        resp = await client.get("/api/content/posts/unsafe/payload.html")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers["content-disposition"].startswith("attachment")
        assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"

    @pytest.mark.asyncio
    async def test_serve_svg_asset_as_attachment(
        self, client: AsyncClient, tmp_content_dir: Path
    ) -> None:
        """SVG assets should be treated as active content for direct delivery."""
        post_dir = tmp_content_dir / "posts" / "unsafe-svg"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "diagram.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            encoding="utf-8",
        )

        resp = await client.get("/api/content/posts/unsafe-svg/diagram.svg")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert resp.headers["content-disposition"].startswith("attachment")
        assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"

    @pytest.mark.asyncio
    async def test_symlink_escape_outside_content_dir_blocked(
        self, client: AsyncClient, tmp_content_dir: Path, tmp_path: Path
    ) -> None:
        """Symlinks pointing outside the content directory are rejected."""
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("sensitive data")

        post_dir = tmp_content_dir / "posts" / "escape"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "secret.txt").symlink_to(outside_file)

        resp = await client.get("/api/content/posts/escape/secret.txt")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_path_returns_404(self, client: AsyncClient) -> None:
        """An empty or root-level path returns opaque 404."""
        resp = await client.get("/api/content/")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_logs_warning(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Path traversal attempts should be logged at WARNING level.

        Use a percent-encoded slash (%2F) so the HTTP client does not normalize
        away the ``..`` segment before the request reaches the server.
        """
        with caplog.at_level(logging.WARNING, logger="backend.api.content"):
            await client.get("/api/content/posts/..%2Findex.toml")
        assert any("Path traversal" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_disallowed_prefix_logs_warning(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Disallowed prefix requests should be logged at WARNING level."""
        with caplog.at_level(logging.WARNING, logger="backend.api.content"):
            await client.get("/api/content/index.toml")
        assert any("Disallowed content prefix" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_content_disposition_escapes_double_quotes_in_filename(
        self, client: AsyncClient, tmp_content_dir: Path
    ) -> None:
        """Content-Disposition filename with double quotes is properly escaped per RFC 6266."""
        post_dir = tmp_content_dir / "posts" / "quoted"
        post_dir.mkdir(parents=True, exist_ok=True)
        # Create an SVG file whose name contains a double-quote character
        filename = 'file"name.svg'
        (post_dir / filename).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8"
        )

        resp = await client.get(f"/api/content/posts/quoted/{filename}")

        assert resp.status_code == 200
        cd_header = resp.headers["content-disposition"]
        assert cd_header.startswith("attachment")
        # The embedded double-quote must be escaped as \" per RFC 6266
        assert '\\"' in cd_header
        # The escaped filename (with \" inside) must appear correctly in the header
        assert 'filename="file\\"name.svg"' in cd_header
