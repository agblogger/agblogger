"""Robustness tests for cross-posting API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport
from sqlalchemy import text

from backend.config import Settings
from backend.services.crosspost_service import DuplicateAccountError
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker


def _get_session_factory(client: AsyncClient) -> async_sessionmaker[Any]:
    """Extract session_factory from a test client's ASGI app state."""
    transport = client._transport
    assert isinstance(transport, ASGITransport)
    app = transport.app
    state = getattr(app, "state", None)
    assert state is not None, "ASGI app has no state attribute"
    factory: async_sessionmaker[Any] = state.session_factory
    return factory


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: Admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
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
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(app_settings) as ac:
        yield ac


class TestCrossPostHistoryCorruptStatus:
    """Issue 1: CrossPostStatus(cp.status) ValueError on corrupt DB data."""

    @pytest.mark.asyncio
    async def test_history_with_unknown_status_returns_200(self, client: AsyncClient) -> None:
        """A cross_posts row with an invalid status value should not crash the endpoint."""
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/crosspost/accounts",
            json={
                "platform": "bluesky",
                "account_name": "test.bsky.social",
                "credentials": {"identifier": "test", "password": "secret"},
            },
            headers=headers,
        )

        session_factory = _get_session_factory(client)
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO cross_posts "
                    "(user_id, post_path, platform, platform_id, "
                    "status, posted_at, error, created_at) "
                    "VALUES (1, 'posts/hello.md', 'bluesky', NULL, "
                    "'unknown_status', NULL, NULL, "
                    "'2026-01-01T00:00:00+00:00')"
                )
            )
            await session.commit()

        resp = await client.get(
            "/api/crosspost/history/posts/hello.md",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "failed"


class TestUpsertSocialAccountRaceCondition:
    """Issue 3: Race condition in _upsert_social_account."""

    @pytest.mark.asyncio
    async def test_upsert_race_condition_returns_409(self, client: AsyncClient) -> None:
        """When create_social_account raises DuplicateAccountError on both calls, return 409."""
        from fastapi import HTTPException

        from backend.api.crosspost import _upsert_social_account
        from backend.schemas.crosspost import SocialAccountCreate

        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200

        session_factory = _get_session_factory(client)

        account_data = SocialAccountCreate(
            platform="bluesky",
            account_name="race.bsky.social",
            credentials={"identifier": "test", "password": "secret"},
        )

        mock_account = AsyncMock()
        mock_account.id = 999
        mock_account.platform = "bluesky"
        mock_account.account_name = "race.bsky.social"

        with (
            patch(
                "backend.api.crosspost.create_social_account",
                new_callable=AsyncMock,
                side_effect=DuplicateAccountError("duplicate"),
            ),
            patch(
                "backend.api.crosspost.get_social_accounts",
                new_callable=AsyncMock,
                return_value=[mock_account],
            ),
            patch(
                "backend.api.crosspost.delete_social_account",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            async with session_factory() as session:
                with pytest.raises(HTTPException) as exc_info:
                    await _upsert_social_account(
                        session,
                        user_id=1,
                        account_data=account_data,
                        secret_key="test-secret-key-with-at-least-32-characters",
                        platform="bluesky",
                        account_name="race.bsky.social",
                    )
                assert exc_info.value.status_code == 409
