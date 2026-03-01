"""Tests for crosspost error handling hardening (M14, M15, M17, L1, L8)."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.crosspost.ssrf import SSRFSafeBackend

if TYPE_CHECKING:
    from pathlib import Path


class TestAsyncDNS:
    """M17: DNS resolution should not block the event loop."""

    async def test_dns_resolution_uses_loop_getaddrinfo(self) -> None:
        """Verify SSRFSafeBackend calls loop.getaddrinfo instead of socket.getaddrinfo."""
        backend = SSRFSafeBackend()
        fake_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

        mock_stream = AsyncMock()
        backend._inner = MagicMock()
        backend._inner.connect_tcp = AsyncMock(return_value=mock_stream)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=fake_addr_info)
            mock_get_loop.return_value = mock_loop

            await backend.connect_tcp("example.com", 443)

            mock_loop.getaddrinfo.assert_awaited_once_with(
                "example.com", 443, proto=socket.IPPROTO_TCP
            )

    async def test_dns_resolution_does_not_call_blocking_getaddrinfo(self) -> None:
        """Verify SSRFSafeBackend does NOT call blocking socket.getaddrinfo."""
        backend = SSRFSafeBackend()
        fake_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

        mock_stream = AsyncMock()
        backend._inner = MagicMock()
        backend._inner.connect_tcp = AsyncMock(return_value=mock_stream)

        with (
            patch("asyncio.get_running_loop") as mock_get_loop,
            patch("socket.getaddrinfo") as mock_blocking,
        ):
            mock_loop = MagicMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=fake_addr_info)
            mock_get_loop.return_value = mock_loop

            await backend.connect_tcp("example.com", 443)

            mock_blocking.assert_not_called()

    async def test_dns_gaierror_raises_connect_error(self) -> None:
        """Verify that DNS failure raises httpcore.ConnectError."""
        backend = SSRFSafeBackend()

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.getaddrinfo = AsyncMock(side_effect=socket.gaierror("Name resolution failed"))
            mock_get_loop.return_value = mock_loop

            with pytest.raises(httpcore.ConnectError, match="DNS resolution failed"):
                await backend.connect_tcp("nonexistent.invalid", 443)


@pytest.mark.slow
class TestRegisterIntegrityError:
    """L1: concurrent registration returns 409 instead of crashing."""

    @pytest.mark.asyncio
    async def test_duplicate_user_integrity_error_returns_409(self, tmp_path: Path) -> None:
        from sqlalchemy.exc import IntegrityError

        from backend.config import Settings
        from tests.conftest import create_test_client

        content = tmp_path / "content"
        content.mkdir()
        (content / "posts").mkdir()
        (content / "assets").mkdir()
        (content / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content / "labels.toml").write_text("[labels]\n")

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            auth_self_registration=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            content_dir=content,
            frontend_dir=tmp_path / "frontend",
        )

        async def patched_flush(self: AsyncSession, objects: object = None) -> None:
            raise IntegrityError("UNIQUE constraint failed", {}, Exception())

        async with create_test_client(settings) as client:
            with patch.object(AsyncSession, "flush", patched_flush):
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "username": "testuser",
                        "email": "test@example.com",
                        "password": "securepass123",
                    },
                )
            assert resp.status_code == 409


class TestSocialAccountCreateDefault:
    """L8: SocialAccountCreate.account_name should default to empty string."""

    def test_account_name_defaults_to_empty_string(self) -> None:
        """SocialAccountCreate without account_name should default to ''."""
        from backend.schemas.crosspost import SocialAccountCreate

        account = SocialAccountCreate(
            platform="bluesky",
            credentials={"access_token": "test"},
        )
        assert account.account_name == ""

    def test_account_name_not_none(self) -> None:
        """SocialAccountCreate.account_name should never be None."""
        from backend.schemas.crosspost import SocialAccountCreate

        account = SocialAccountCreate(
            platform="bluesky",
            credentials={"access_token": "test"},
        )
        assert account.account_name is not None

    def test_account_name_explicit_value(self) -> None:
        """SocialAccountCreate with explicit account_name should preserve it."""
        from backend.schemas.crosspost import SocialAccountCreate

        account = SocialAccountCreate(
            platform="bluesky",
            account_name="@test.bsky.social",
            credentials={"access_token": "test"},
        )
        assert account.account_name == "@test.bsky.social"
