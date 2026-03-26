"""Tests for crosspost error handling hardening (M14, M15, M17, L1, L8)."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import pytest

from backend.crosspost.ssrf import SSRFSafeBackend


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

    def test_account_name_explicit_value(self) -> None:
        """SocialAccountCreate with explicit account_name should preserve it."""
        from backend.schemas.crosspost import SocialAccountCreate

        account = SocialAccountCreate(
            platform="bluesky",
            account_name="@test.bsky.social",
            credentials={"access_token": "test"},
        )
        assert account.account_name == "@test.bsky.social"
