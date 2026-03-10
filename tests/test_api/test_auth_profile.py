"""Profile update integration tests."""

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
    posts_dir = tmp_content_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        auth_self_registration=False,
        auth_invites_enabled=True,
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login_admin(client: AsyncClient) -> dict[str, str]:
    """Login as admin and return headers with CSRF token."""
    resp = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


class TestUsernameFormatValidation:
    async def test_register_rejects_username_with_spaces(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "bad user",
                "email": "bad@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 422

    async def test_register_rejects_username_with_special_chars(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "user:name",
                "email": "u@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 422

    async def test_register_rejects_username_starting_with_dot(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": ".hidden",
                "email": "h@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 422

    async def test_register_accepts_valid_username(
        self, client: AsyncClient
    ) -> None:
        headers = await _login_admin(client)
        resp = await client.post("/api/auth/invites", json={}, headers=headers)
        assert resp.status_code == 201
        code = resp.json()["invite_code"]
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "valid-user_1.name",
                "email": "valid@example.com",
                "password": "password123",
                "invite_code": code,
            },
            headers=headers,
        )
        assert resp.status_code == 201
