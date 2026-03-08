"""Tests for cross-endpoint content write serialization lock."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

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

    @pytest.mark.asyncio
    async def test_post_update_uses_content_write_lock(self, client: AsyncClient) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post first
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Update Lock Test",
                "body": "Original content",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        # Now inject the counting lock and update
        lock = _CountingLock()
        app = client._transport.app  # type: ignore[attr-defined]
        app.state.content_write_lock = lock

        resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Updated Lock Test",
                "body": "Updated content",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert lock.enter_count >= 1

    @pytest.mark.asyncio
    async def test_post_delete_uses_content_write_lock(self, client: AsyncClient) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post first
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Delete Lock Test",
                "body": "Content to delete",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        # Now inject the counting lock and delete
        lock = _CountingLock()
        app = client._transport.app  # type: ignore[attr-defined]
        app.state.content_write_lock = lock

        resp = await client.delete(
            f"/api/posts/{file_path}",
            headers=headers,
        )
        assert resp.status_code == 204
        assert lock.enter_count >= 1


class TestWriteLockSerialization:
    """The content write lock should serialize concurrent write operations."""

    @pytest.mark.asyncio
    async def test_concurrent_creates_are_serialized(self, client: AsyncClient) -> None:
        """Two concurrent post creates should not overlap execution."""
        from backend.filesystem.content_manager import ContentManager

        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        execution_log: list[str] = []
        real_write = ContentManager.write_post

        def _tracking_write(self: ContentManager, file_path: str, post_data: Any) -> None:
            name = "A" if "Body A" in post_data.content else "B"
            execution_log.append(f"start:{name}")
            real_write(self, file_path, post_data)
            execution_log.append(f"end:{name}")

        with patch.object(ContentManager, "write_post", new=_tracking_write):
            results = await asyncio.gather(
                client.post(
                    "/api/posts",
                    json={"title": "Lock A", "body": "Body A", "labels": [], "is_draft": False},
                    headers=headers,
                ),
                client.post(
                    "/api/posts",
                    json={"title": "Lock B", "body": "Body B", "labels": [], "is_draft": False},
                    headers=headers,
                ),
            )

        assert all(r.status_code == 201 for r in results), [r.text for r in results]
        # Under serialization, operations should NOT interleave.
        # The log must be [start:X, end:X, start:Y, end:Y] (not start:X, start:Y, ...).
        assert len(execution_log) == 4
        first = execution_log[0].split(":", 1)[1]
        second = "B" if first == "A" else "A"
        assert execution_log == [
            f"start:{first}",
            f"end:{first}",
            f"start:{second}",
            f"end:{second}",
        ]
