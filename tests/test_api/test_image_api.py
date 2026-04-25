"""Tests for site image admin endpoints and public /image.<ext> routes."""

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


class TestUploadOgImage:
    @pytest.mark.asyncio
    async def test_upload_png_saves_file_and_returns_settings(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.png", png_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["image"] == "assets/image.png"
        assert (app_settings.content_dir / "assets" / "image.png").exists()

    @pytest.mark.asyncio
    async def test_upload_jpeg_accepted(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        jpg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 20

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.jpg", jpg_data, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["image"] == "assets/image.jpg"
        assert (app_settings.content_dir / "assets" / "image.jpg").exists()

    @pytest.mark.asyncio
    async def test_upload_webp_accepted(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        webp_data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.webp", webp_data, "image/webp")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["image"] == "assets/image.webp"

    @pytest.mark.asyncio
    async def test_rejects_unsupported_type(self, client: AsyncClient) -> None:
        token = await _login(client)

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.svg", b"<svg/>", "image/svg+xml")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.png", b"PNG", "image/png")},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self, client: AsyncClient) -> None:
        token = await _login(client)
        large_data = b"x" * (5 * 1024 * 1024 + 1)

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.png", large_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_gif_accepted(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        gif_data = b"GIF89a" + b"\x00" * 20

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.gif", gif_data, "image/gif")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["image"] == "assets/image.gif"
        assert (app_settings.content_dir / "assets" / "image.gif").exists()

    @pytest.mark.asyncio
    async def test_upload_without_content_type_rejected(self, client: AsyncClient) -> None:
        """A multipart file part with no Content-Type must return 422, not 500."""
        token = await _login(client)

        resp = await client.post(
            "/api/admin/image",
            files={"file": ("og.png", b"\x89PNG", "")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 422


class TestRemoveOgImage:
    @pytest.mark.asyncio
    async def test_remove_clears_image(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        await client.post(
            "/api/admin/image",
            files={"file": ("og.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.delete(
            "/api/admin/image",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["image"] is None
        assert not (app_settings.content_dir / "assets" / "image.png").exists()

    @pytest.mark.asyncio
    async def test_remove_when_none_is_ok(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.delete(
            "/api/admin/image",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["image"] is None

    @pytest.mark.asyncio
    async def test_remove_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/admin/image")
        assert resp.status_code == 401


class TestPublicOgImageRoutes:
    @pytest.mark.asyncio
    async def test_returns_404_when_not_configured(self, client: AsyncClient) -> None:
        resp = await client.get("/image.png")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_serves_png(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        await client.post(
            "/api/admin/image",
            files={"file": ("og.png", png_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/image.png")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == png_data

    @pytest.mark.asyncio
    async def test_serves_gif(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        gif_data = b"GIF89a" + b"\x00" * 20
        await client.post(
            "/api/admin/image",
            files={"file": ("og.gif", gif_data, "image/gif")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/image.gif")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/gif"
        assert resp.content == gif_data

    @pytest.mark.asyncio
    async def test_serves_jpg(self, client: AsyncClient, app_settings: Settings) -> None:
        token = await _login(client)
        jpg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        await client.post(
            "/api/admin/image",
            files={"file": ("og.jpg", jpg_data, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/image.jpg")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == jpg_data

    @pytest.mark.asyncio
    async def test_returns_404_for_format_mismatch(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        await client.post(
            "/api/admin/image",
            files={"file": ("og.png", b"PNG", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get("/image.jpg")

        assert resp.status_code == 404


class TestSiteSettingsExposesOgImage:
    @pytest.mark.asyncio
    async def test_get_site_returns_image_field(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        resp = await client.get(
            "/api/admin/site",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "image" in resp.json()
        assert resp.json()["image"] is None

    @pytest.mark.asyncio
    async def test_get_site_reflects_uploaded_image(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        await client.post(
            "/api/admin/image",
            files={"file": ("og.png", b"\x89PNG", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get(
            "/api/admin/site",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["image"] == "assets/image.png"
