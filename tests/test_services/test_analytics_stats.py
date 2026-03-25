"""Tests for analytics stats proxy methods (Task 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.base import DurableBase
from backend.services.analytics_service import (
    _stats_request,
    fetch_breakdown,
    fetch_path_hits,
    fetch_path_referrers,
    fetch_total_stats,
    fetch_view_count,
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


# ── fetch_total_stats ──────────────────────────────────────────────────────────


async def test_fetch_total_stats_returns_correct_data(session: AsyncSession) -> None:
    """fetch_total_stats maps GoatCounter response to TotalStatsResponse."""
    fake_response = {"total": 120, "total_unique": 85}

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_total_stats(start="2025-01-01", end="2025-01-31")

    assert result.total_views == 120
    assert result.total_unique == 85


async def test_fetch_total_stats_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_total_stats returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_total_stats()

    assert result is None


# ── fetch_path_hits ────────────────────────────────────────────────────────────


async def test_fetch_path_hits_returns_correct_data(session: AsyncSession) -> None:
    """fetch_path_hits maps GoatCounter hits to PathHitsResponse."""
    fake_response = {
        "hits": [
            {"id": 1, "path": "/post/hello", "count": 42, "count_unique": 30},
            {"id": 2, "path": "/post/world", "count": 17, "count_unique": 12},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits(start="2025-01-01", end="2025-01-31")

    assert len(result.paths) == 2
    assert result.paths[0].path_id == 1
    assert result.paths[0].path == "/post/hello"
    assert result.paths[0].views == 42
    assert result.paths[0].unique == 30
    assert result.paths[1].path_id == 2
    assert result.paths[1].path == "/post/world"
    assert result.paths[1].views == 17


async def test_fetch_path_hits_skips_entries_with_missing_id(session: AsyncSession) -> None:
    """Issue 7: entries without an id field should be skipped."""
    fake_response = {
        "hits": [
            {"id": 1, "path": "/post/hello", "count": 42, "count_unique": 30},
            {"path": "/post/no-id", "count": 5, "count_unique": 3},  # no id
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits()

    assert len(result.paths) == 1
    assert result.paths[0].path_id == 1


async def test_fetch_path_hits_skips_entries_with_zero_id(session: AsyncSession) -> None:
    """Issue 7: entries with id=0 should be skipped."""
    fake_response = {
        "hits": [
            {"id": 0, "path": "/post/zero", "count": 10, "count_unique": 5},
            {"id": 2, "path": "/post/valid", "count": 7, "count_unique": 4},
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits()

    assert len(result.paths) == 1
    assert result.paths[0].path_id == 2


async def test_fetch_path_hits_skips_entries_with_empty_path(session: AsyncSession) -> None:
    """Suggestion 6: entries with empty path should be skipped."""
    fake_response = {
        "hits": [
            {"id": 1, "path": "", "count": 10, "count_unique": 5},
            {"id": 2, "path": "/post/valid", "count": 7, "count_unique": 4},
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits()

    assert len(result.paths) == 1
    assert result.paths[0].path_id == 2


async def test_fetch_path_hits_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_path_hits returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_hits()

    assert result is None


# ── fetch_path_referrers ───────────────────────────────────────────────────────


async def test_fetch_path_referrers_returns_correct_data(session: AsyncSession) -> None:
    """fetch_path_referrers maps GoatCounter referrer data to PathReferrersResponse."""
    fake_response = {
        "referrers": [
            {"name": "https://example.com", "count": 8},
            {"name": "Direct", "count": 5},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_referrers(path_id=42)

    assert result.path_id == 42
    assert len(result.referrers) == 2
    assert result.referrers[0].referrer == "https://example.com"
    assert result.referrers[0].count == 8
    assert result.referrers[1].referrer == "Direct"


async def test_fetch_path_referrers_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_path_referrers returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(path_id=7)

    assert result is None


# ── fetch_breakdown ────────────────────────────────────────────────────────────


async def test_fetch_breakdown_returns_correct_data(session: AsyncSession) -> None:
    """fetch_breakdown maps GoatCounter stats to BreakdownResponse."""
    fake_response = {
        "stats": [
            {"name": "Chrome", "count": 60, "percent": 60.0},
            {"name": "Firefox", "count": 40, "percent": 40.0},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_breakdown("browsers", start="2025-01-01")

    assert result.category == "browsers"
    assert len(result.entries) == 2
    assert result.entries[0].name == "Chrome"
    assert result.entries[0].count == 60
    assert result.entries[0].percent == 60.0
    assert result.entries[1].name == "Firefox"


async def test_fetch_breakdown_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_breakdown returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown("browsers")

    assert result is None


# ── fetch_view_count ───────────────────────────────────────────────────────────


async def test_fetch_view_count_returns_count_when_enabled(session: AsyncSession) -> None:
    """fetch_view_count returns the view count for a path when show_views_on_posts is enabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    fake_response = {
        "hits": [
            {"path": "/post/hello", "count": 99, "count_unique": 70},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        count = await fetch_view_count(session, "/post/hello")

    assert count == 99


async def test_fetch_view_count_returns_none_when_disabled(session: AsyncSession) -> None:
    """fetch_view_count returns None when show_views_on_posts is False."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": [{"path": "/post/hello", "count": 99}]},
    ) as mock_req:
        count = await fetch_view_count(session, "/post/hello")

    assert count is None
    mock_req.assert_not_called()


async def test_fetch_view_count_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_view_count returns None when GoatCounter is unavailable."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        count = await fetch_view_count(session, "/post/hello")

    assert count is None


async def test_fetch_view_count_returns_zero_for_unknown_path(session: AsyncSession) -> None:
    """fetch_view_count returns 0 when the path is not present in GoatCounter hits."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    fake_response = {
        "hits": [
            {"path": "/post/other", "count": 5},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        count = await fetch_view_count(session, "/post/hello")

    assert count == 0


# ── fetch_* returns None when GoatCounter is down (Issue 5) ───────────────────


async def test_fetch_total_stats_returns_none_when_unavailable() -> None:
    """fetch_total_stats returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_total_stats()

    assert result is None


async def test_fetch_path_hits_returns_none_when_unavailable() -> None:
    """fetch_path_hits returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_hits()

    assert result is None


async def test_fetch_path_referrers_returns_none_when_unavailable() -> None:
    """fetch_path_referrers returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(path_id=7)

    assert result is None


async def test_fetch_breakdown_returns_none_when_unavailable() -> None:
    """fetch_breakdown returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown("browsers")

    assert result is None


# ── _stats_request error handling (Test 11) ───────────────────────────────────


async def test_stats_request_returns_none_on_http_500() -> None:
    """_stats_request returns None when GoatCounter responds with HTTP 500."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=MagicMock(status_code=500),
    )
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

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


async def test_stats_request_returns_none_on_timeout() -> None:
    """_stats_request returns None on network timeout."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=MagicMock())
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


async def test_stats_request_returns_none_on_invalid_json() -> None:
    """_stats_request returns None when the response body is not valid JSON."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = ValueError("invalid JSON")
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

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
