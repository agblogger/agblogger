"""Tests for the analytics service settings management."""

from __future__ import annotations

import builtins
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

import backend.services.analytics_service as svc
from backend.models.base import DurableBase
from backend.services.analytics_service import (
    _load_token,
    close_analytics_client,
    get_analytics_settings,
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


def test_load_token_returns_cached_without_rereading_file() -> None:
    """_load_token returns the cached token without re-opening the file when already set."""
    svc._goatcounter_token = "cached-token"

    open_mock = MagicMock()
    with patch.object(builtins, "open", open_mock):
        token = _load_token()

    assert token == "cached-token"
    open_mock.assert_not_called()


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
