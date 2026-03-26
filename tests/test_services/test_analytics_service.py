"""Tests for the analytics service settings management."""

from __future__ import annotations

import builtins
from io import StringIO
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.services.analytics_service as svc
from backend.models.base import DurableBase
from backend.services.analytics_service import (
    _load_token,
    close_analytics_client,
    get_analytics_settings,
    record_hit,
    update_analytics_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


async def test_get_default_settings(session: AsyncSession) -> None:
    """get_analytics_settings returns defaults when no row exists."""
    result = await get_analytics_settings(session)
    assert result.analytics_enabled is True
    assert result.show_views_on_posts is False


async def test_update_settings_creates_row(session: AsyncSession) -> None:
    """update_analytics_settings creates a row on first call."""
    result = await update_analytics_settings(
        session, analytics_enabled=False, show_views_on_posts=True
    )
    assert result.analytics_enabled is False
    assert result.show_views_on_posts is True

    # Verify persisted
    fetched = await get_analytics_settings(session)
    assert fetched.analytics_enabled is False
    assert fetched.show_views_on_posts is True


async def test_update_settings_partial(session: AsyncSession) -> None:
    """update_analytics_settings applies partial updates, leaving unchanged fields intact."""
    # Create initial row
    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=False)

    # Partial update: only change analytics_enabled
    result = await update_analytics_settings(
        session, analytics_enabled=False, show_views_on_posts=None
    )
    assert result.analytics_enabled is False
    assert result.show_views_on_posts is False  # unchanged

    # Partial update: only change show_views_on_posts
    result2 = await update_analytics_settings(
        session, analytics_enabled=None, show_views_on_posts=True
    )
    assert result2.analytics_enabled is False  # unchanged from previous
    assert result2.show_views_on_posts is True


# ── _load_token tests (Issue 3) ────────────────────────────────────────────────


def test_load_token_reads_and_caches_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_load_token reads token from file and caches it in the module global."""
    with patch.object(builtins, "open", return_value=StringIO("my-secret-token\n")):
        token = _load_token()

    assert token == "my-secret-token"
    assert svc._goatcounter_token == "my-secret-token"


def test_load_token_empty_file_returns_none_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_load_token returns None and logs a warning when token file is empty."""
    with (
        patch.object(builtins, "open", return_value=StringIO("   \n")),
        caplog.at_level("WARNING", logger="backend.services.analytics_service"),
    ):
        token = _load_token()

    assert token is None
    assert any("empty" in r.message for r in caplog.records)


def test_load_token_file_not_found_first_miss_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_load_token returns None and logs WARNING on first FileNotFoundError."""
    with (
        patch.object(builtins, "open", side_effect=FileNotFoundError()),
        caplog.at_level("WARNING", logger="backend.services.analytics_service"),
    ):
        token = _load_token()

    assert token is None
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_load_token_file_not_found_subsequent_miss_debugs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_load_token logs at DEBUG level on subsequent FileNotFoundError misses."""
    # First miss: sets _token_warning_issued = True
    with patch.object(builtins, "open", side_effect=FileNotFoundError()):
        _load_token()

    caplog.clear()

    with (
        patch.object(builtins, "open", side_effect=FileNotFoundError()),
        caplog.at_level("DEBUG", logger="backend.services.analytics_service"),
    ):
        token = _load_token()

    assert token is None
    # Should log DEBUG, not WARNING
    assert any(r.levelname == "DEBUG" for r in caplog.records)
    assert not any(r.levelname == "WARNING" for r in caplog.records)


def test_load_token_permission_error_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_load_token returns None and logs ERROR on PermissionError (OSError)."""
    with (
        patch.object(builtins, "open", side_effect=PermissionError("access denied")),
        caplog.at_level("ERROR", logger="backend.services.analytics_service"),
    ):
        token = _load_token()

    assert token is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_token_rereads_file_when_cached_token_exists() -> None:
    """_load_token refreshes the cached token from disk on every call."""
    svc._goatcounter_token = "cached-token"

    with patch.object(builtins, "open", return_value=StringIO("fresh-token\n")):
        token = _load_token()

    assert token == "fresh-token"
    assert svc._goatcounter_token == "fresh-token"


# ── close_analytics_client tests ──────────────────────────────────────────────


async def test_close_analytics_client_sets_global_to_none() -> None:
    """close_analytics_client closes the httpx client and sets _http_client to None."""
    from backend.services.analytics_service import _get_http_client

    # Create a client
    client = _get_http_client()
    assert client is not None
    assert svc._http_client is not None

    await close_analytics_client()

    assert svc._http_client is None


# ── Issue 3: httpx client timeout must not be None ────────────────────────────


def test_http_client_has_finite_timeout() -> None:
    """_get_http_client creates a client with finite (non-None) timeout values."""
    from backend.services.analytics_service import _get_http_client

    client = _get_http_client()
    # The default timeout should not be None (infinite)
    assert client.timeout.connect is not None
    assert client.timeout.read is not None
    assert client.timeout.write is not None
    assert client.timeout.pool is not None


# ── Issue 1: record_hit must not swallow programming bugs ─────────────────────


async def test_record_hit_propagates_programming_error(
    session: AsyncSession,
) -> None:
    """A TypeError inside record_hit (programming bug) must propagate, not be swallowed."""
    mock_client = MagicMock()
    # Simulate a programming bug: post() raises TypeError
    mock_client.post = AsyncMock(side_effect=TypeError("bad argument"))

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
        pytest.raises(TypeError, match="bad argument"),
    ):
        await record_hit(
            session=session,
            path="/post/hello",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )


async def test_record_hit_catches_http_error(
    session: AsyncSession,
) -> None:
    """An httpx.HTTPError during hit recording is caught and logged (not raised)."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=MagicMock(status_code=500),
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
            return_value="test-token",
        ),
    ):
        # Must not raise
        await record_hit(
            session=session,
            path="/post/hello",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )


# ── Issue 1: _stats_request must not swallow programming bugs ─────────────────


async def test_stats_request_propagates_type_error() -> None:
    """A TypeError inside _stats_request (programming bug) must propagate."""
    from backend.services.analytics_service import _stats_request

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=TypeError("unexpected keyword"))

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
        pytest.raises(TypeError, match="unexpected keyword"),
    ):
        await _stats_request("/api/v0/stats/total")


async def test_stats_request_catches_http_error_returns_none() -> None:
    """An httpx.HTTPError in _stats_request returns None gracefully."""
    import httpx

    from backend.services.analytics_service import _stats_request

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused", request=MagicMock())
    )

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
    ):
        result = await _stats_request("/api/v0/stats/total")

    assert result is None


# ── Issue 9: _stats_request token-None path ───────────────────────────────────


async def test_stats_request_returns_none_when_token_is_none() -> None:
    """_stats_request returns None without making HTTP calls when token is None."""
    from backend.services.analytics_service import _stats_request

    mock_client = MagicMock()
    mock_client.get = AsyncMock()

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
        result = await _stats_request("/api/v0/stats/total")

    assert result is None
    mock_client.get.assert_not_called()


# ── Suggestion 3: _stats_request log includes params ──────────────────────────


async def test_stats_request_log_includes_params(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When _stats_request fails, the log message includes query parameters."""
    import httpx

    from backend.services.analytics_service import _stats_request

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused", request=MagicMock())
    )

    with (
        patch(
            "backend.services.analytics_service._get_http_client",
            return_value=mock_client,
        ),
        patch(
            "backend.services.analytics_service._load_token",
            return_value="test-token",
        ),
        caplog.at_level("WARNING", logger="backend.services.analytics_service"),
    ):
        await _stats_request("/api/v0/stats/total", {"start": "2025-01-01"})

    assert any("start" in r.message for r in caplog.records)


# ── Suggestion 4: Settings upsert handles IntegrityError ──────────────────────


async def test_update_settings_handles_integrity_error_on_insert(
    session: AsyncSession,
) -> None:
    """update_analytics_settings recovers from IntegrityError during initial insert.

    Simulates a race condition where another request creates the row between
    our SELECT (returning None) and our INSERT. The function should catch the
    IntegrityError and fall back to updating the existing row.
    """
    from sqlalchemy.exc import IntegrityError

    from backend.models.analytics import AnalyticsSettings

    # Pre-insert a row to simulate the concurrent insert
    existing = AnalyticsSettings(analytics_enabled=True, show_views_on_posts=False)
    session.add(existing)
    await session.commit()

    # Mock the first SELECT to return None (simulating the race condition),
    # but let flush raise IntegrityError. After rollback, the retry SELECT
    # should find the existing row.
    original_execute = session.execute
    select_call_count = 0

    async def patched_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal select_call_count
        from sqlalchemy import Select

        if isinstance(stmt, Select):
            select_call_count += 1
            if select_call_count == 1:
                # First SELECT: pretend the row doesn't exist (race window)
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                return result
        return await original_execute(stmt, *args, **kwargs)

    async def patched_flush(*args: Any, **kwargs: Any) -> None:
        raise IntegrityError("UNIQUE constraint", {}, Exception())

    with (
        patch.object(session, "execute", side_effect=patched_execute),
        patch.object(session, "flush", side_effect=patched_flush),
    ):
        result = await update_analytics_settings(
            session, analytics_enabled=False, show_views_on_posts=True
        )

    assert result.analytics_enabled is False
    assert result.show_views_on_posts is True


# ── Issue 4: fire_background_hit shared helper ────────────────────────────────


async def test_fire_background_hit_schedules_task() -> None:
    """fire_background_hit creates a background task that calls record_hit."""
    import asyncio

    from backend.services.analytics_service import fire_background_hit

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent/1.0"}

    mock_session_factory = MagicMock()
    mock_session_ctx = AsyncMock()
    mock_session_factory.return_value.__aenter__ = mock_session_ctx
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.services.analytics_service.record_hit",
        new_callable=AsyncMock,
    ) as mock_record:
        fire_background_hit(
            request=mock_request,
            session_factory=mock_session_factory,
            path="/post/hello",
            user=None,
        )
        # Allow the background task to run
        await asyncio.sleep(0.01)

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["path"] == "/post/hello"
    assert call_kwargs["client_ip"] == "10.0.0.1"
    assert call_kwargs["user_agent"] == "TestAgent/1.0"
    assert call_kwargs["user"] is None


async def test_fire_background_hit_catches_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """fire_background_hit catches and logs exceptions from the background task."""
    import asyncio
    import logging

    from backend.services.analytics_service import fire_background_hit

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent/1.0"}

    # session_factory raises to simulate a failure
    mock_session_factory = MagicMock(side_effect=RuntimeError("pool exhausted"))

    with (
        caplog.at_level(logging.WARNING, logger="backend.services.analytics_service"),
    ):
        fire_background_hit(
            request=mock_request,
            session_factory=mock_session_factory,
            path="/post/hello",
            user=None,
        )
        await asyncio.sleep(0.01)

    assert any("Background analytics hit failed" in r.message for r in caplog.records)


async def test_fire_background_hit_drops_when_capacity_is_reached(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Background hit scheduling should shed load instead of growing without bound."""
    import asyncio
    import logging

    from backend.services.analytics_service import fire_background_hit

    blocker = asyncio.Event()

    async def hold_slot() -> None:
        await blocker.wait()

    occupied_task = asyncio.create_task(hold_slot())
    svc._background_tasks.add(occupied_task)

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent/1.0"}

    mock_session_factory = MagicMock()

    try:
        with (
            patch.object(svc, "_MAX_BACKGROUND_TASKS", 1, create=True),
            patch(
                "backend.services.analytics_service.record_hit",
                new_callable=AsyncMock,
            ) as mock_record,
            caplog.at_level(logging.WARNING, logger="backend.services.analytics_service"),
        ):
            fire_background_hit(
                request=mock_request,
                session_factory=mock_session_factory,
                path="/post/hello",
                user=None,
            )
            await asyncio.sleep(0.01)

        mock_record.assert_not_called()
        assert any("dropping analytics hit" in r.message.lower() for r in caplog.records)
    finally:
        blocker.set()
        await occupied_task
        svc._background_tasks.discard(occupied_task)
