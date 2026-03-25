"""Tests for analytics stats proxy methods (Task 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.base import DurableBase
from backend.services.analytics_service import (
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
        result = await fetch_total_stats(session, start="2025-01-01", end="2025-01-31")

    assert result.total_views == 120
    assert result.total_unique == 85


async def test_fetch_total_stats_returns_zeros_when_unavailable(session: AsyncSession) -> None:
    """fetch_total_stats returns zero counts when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_total_stats(session)

    assert result.total_views == 0
    assert result.total_unique == 0


# ── fetch_path_hits ────────────────────────────────────────────────────────────


async def test_fetch_path_hits_returns_correct_data(session: AsyncSession) -> None:
    """fetch_path_hits maps GoatCounter hits to PathHitsResponse."""
    fake_response = {
        "hits": [
            {"path": "/post/hello", "count": 42, "count_unique": 30},
            {"path": "/post/world", "count": 17, "count_unique": 12},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits(session, start="2025-01-01", end="2025-01-31")

    assert len(result.paths) == 2
    assert result.paths[0].path == "/post/hello"
    assert result.paths[0].views == 42
    assert result.paths[0].unique == 30
    assert result.paths[1].path == "/post/world"
    assert result.paths[1].views == 17


async def test_fetch_path_hits_returns_empty_when_unavailable(session: AsyncSession) -> None:
    """fetch_path_hits returns empty paths list when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_hits(session)

    assert result.paths == []


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
        result = await fetch_path_referrers(session, path_id=42)

    assert result.path_id == 42
    assert len(result.referrers) == 2
    assert result.referrers[0].referrer == "https://example.com"
    assert result.referrers[0].count == 8
    assert result.referrers[1].referrer == "Direct"


async def test_fetch_path_referrers_returns_empty_when_unavailable(
    session: AsyncSession,
) -> None:
    """fetch_path_referrers returns empty referrers list when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(session, path_id=7)

    assert result.path_id == 7
    assert result.referrers == []


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
        result = await fetch_breakdown(session, "browsers", start="2025-01-01")

    assert result.category == "browsers"
    assert len(result.entries) == 2
    assert result.entries[0].name == "Chrome"
    assert result.entries[0].count == 60
    assert result.entries[0].percent == 60.0
    assert result.entries[1].name == "Firefox"


async def test_fetch_breakdown_returns_empty_when_unavailable(session: AsyncSession) -> None:
    """fetch_breakdown returns empty entries when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown(session, "browsers")

    assert result.category == "browsers"
    assert result.entries == []


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
