"""Tests for cross-endpoint content write serialization lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


class _CountingLock:
    def __init__(self) -> None:
        self.enter_count = 0

    async def __aenter__(self) -> _CountingLock:
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


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


class TestWriteLocking:
    @pytest.mark.asyncio
    async def test_post_create_uses_content_write_lock(self, client: AsyncClient) -> None:
        token = await _login(client)
        lock = _CountingLock()
        app = client._transport.app  # type: ignore[attr-defined]
        app.state.content_write_lock = lock

        resp = await client.post(
            "/api/posts",
            json={
                "title": "Lock Test Post",
                "body": "Hello",
                "labels": [],
                "is_draft": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert lock.enter_count >= 1

    @pytest.mark.asyncio
    async def test_sync_commit_uses_content_write_lock(self, client: AsyncClient) -> None:
        token = await _login(client)
        lock = _CountingLock()
        app = client._transport.app  # type: ignore[attr-defined]
        app.state.content_write_lock = lock

        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert lock.enter_count >= 1
