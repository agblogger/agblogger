"""Tests for analytics hit recording (Task 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.base import DurableBase
from backend.services.analytics_service import record_hit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from backend.models.user import User


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Return a mock httpx.AsyncClient."""
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=202))
    return client


async def test_record_hit_sends_to_goatcounter(
    session: AsyncSession,
    mock_http_client: MagicMock,
) -> None:
    """Unauthenticated non-bot requests send a hit to GoatCounter."""
    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_http_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            user=None,
        )

    mock_http_client.post.assert_called_once()
    call_kwargs = mock_http_client.post.call_args
    assert "/api/v0/count" in call_kwargs.args[0]
    payload = call_kwargs.kwargs["json"]
    assert payload["hits"][0]["path"] == "/post/hello-world"
    assert payload["hits"][0]["ip"] == "1.2.3.4"


async def test_record_hit_skips_authenticated_user(
    session: AsyncSession,
    mock_http_client: MagicMock,
) -> None:
    """Authenticated users do not generate analytics hits."""
    mock_user: User = MagicMock()

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_http_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=mock_user,
        )

    mock_http_client.post.assert_not_called()


async def test_record_hit_skips_bots(
    session: AsyncSession,
    mock_http_client: MagicMock,
) -> None:
    """Bot user agents do not generate analytics hits."""
    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_http_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="66.249.70.1",
            user_agent=("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
            user=None,
        )

    mock_http_client.post.assert_not_called()


async def test_record_hit_skips_when_disabled(
    session: AsyncSession,
    mock_http_client: MagicMock,
) -> None:
    """No hit is sent when analytics_enabled is False."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_http_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )

    mock_http_client.post.assert_not_called()


async def test_record_hit_network_error_is_silent(
    session: AsyncSession,
) -> None:
    """A network error during hit recording is silently absorbed — no exception raised."""
    failing_client = MagicMock()
    failing_client.post = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=failing_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        # Must not raise.
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )


async def test_record_hit_401_logs_warning(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 401 response from GoatCounter is logged as a warning, not silently discarded."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=MagicMock(status_code=401),
    )
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="invalid-token",
        ),
        caplog.at_level("WARNING", logger="backend.services.analytics_service"),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )

    assert any("Failed to record analytics hit" in r.message for r in caplog.records)


async def test_record_hit_no_http_call_when_token_none(
    session: AsyncSession,
) -> None:
    """When _load_token returns None, the HTTP client is never called."""
    mock_client = MagicMock()
    mock_client.post = AsyncMock()

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value=None,
        ),
    ):
        await record_hit(
            session=session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )

    mock_client.post.assert_not_called()
