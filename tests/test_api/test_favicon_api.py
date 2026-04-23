"""Tests for favicon admin endpoints and public /favicon.ico route."""

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
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
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
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestUploadFavicon:
    @pytest.mark.asyncio
    async def test_upload_png_saves_file_and_returns_settings(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

        resp = await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", png_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["favicon"] == "assets/favicon.png"
        assert (app_settings.content_dir / "assets" / "favicon.png").exists()

    @pytest.mark.asyncio
    async def test_upload_svg_accepted(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        svg_data = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"

        resp = await client.post(
            "/api/admin/favicon",
            files={"file": ("icon.svg", svg_data, "image/svg+xml")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["favicon"] == "assets/favicon.svg"

    @pytest.mark.asyncio
    async def test_rejects_unsupported_type(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.gif", b"GIF89a", "image/gif")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", b"PNG", "image/png")},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self, client: AsyncClient) -> None:
        token = await _login(client)
        large_data = b"x" * (2 * 1024 * 1024 + 1)

        resp = await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", large_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 413


class TestRemoveFavicon:
    @pytest.mark.asyncio
    async def test_remove_clears_favicon(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        # Upload first
        await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.delete(
            "/api/admin/favicon",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["favicon"] is None
        assert not (app_settings.content_dir / "assets" / "favicon.png").exists()

    @pytest.mark.asyncio
    async def test_remove_when_none_is_ok(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.delete(
            "/api/admin/favicon",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["favicon"] is None

    @pytest.mark.asyncio
    async def test_remove_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/admin/favicon")
        assert resp.status_code == 401


class TestPublicFaviconRoute:
    @pytest.mark.asyncio
    async def test_returns_404_when_not_configured(self, client: AsyncClient) -> None:
        resp = await client.get("/favicon.ico")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_png_when_configured(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", png_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/favicon.ico")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == png_data

    @pytest.mark.asyncio
    async def test_returns_svg_with_correct_content_type(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        svg_data = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        await client.post(
            "/api/admin/favicon",
            files={"file": ("icon.svg", svg_data, "image/svg+xml")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/favicon.ico")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"


class TestFaviconHtmlInjection:
    @pytest.mark.asyncio
    async def test_index_html_has_no_favicon_link_when_unset(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        frontend_dir = app_settings.frontend_dir
        frontend_dir.mkdir(parents=True, exist_ok=True)
        (frontend_dir / "index.html").write_text(
            '<!doctype html><html><head></head><body><div id="root"></div></body></html>'
        )

        resp = await client.get("/")
        assert resp.status_code == 200
        assert '<link rel="icon"' not in resp.text

    @pytest.mark.asyncio
    async def test_index_html_has_favicon_link_when_set(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        frontend_dir = app_settings.frontend_dir
        frontend_dir.mkdir(parents=True, exist_ok=True)
        (frontend_dir / "index.html").write_text(
            '<!doctype html><html><head></head><body><div id="root"></div></body></html>'
        )
        token = await _login(client)
        await client.post(
            "/api/admin/favicon",
            files={"file": ("favicon.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/")
        assert resp.status_code == 200
        assert '<link rel="icon" href="/favicon.ico">' in resp.text
