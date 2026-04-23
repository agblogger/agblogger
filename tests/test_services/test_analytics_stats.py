"""Tests for analytics stats proxy methods (Task 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.base import DurableBase
from backend.schemas.analytics import (
    BreakdownDetailEntry,
)
from backend.services.analytics_service import (
    _stats_request,
    fetch_dashboard,
    fetch_path_referrers,
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


# ── fetch_path_referrers ───────────────────────────────────────────────────────


async def test_fetch_path_referrers_returns_correct_data(session: AsyncSession) -> None:
    """fetch_path_referrers maps GoatCounter referrer data to PathReferrersResponse."""
    fake_response = {
        "refs": [
            {"name": "https://example.com", "count": 8},
            {"name": "", "count": 5, "ref_scheme": "o"},
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


async def test_fetch_path_referrers_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_path_referrers returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(session, path_id=7)

    assert result is None


async def test_fetch_path_referrers_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """Referrer admin stats are gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"refs": []},
    ) as mock_req:
        result = await fetch_path_referrers(session, path_id=7)

    assert result is None
    mock_req.assert_not_called()


# ── fetch_view_count ───────────────────────────────────────────────────────────


async def test_fetch_view_count_returns_count_when_enabled(session: AsyncSession) -> None:
    """fetch_view_count returns the view count for a path when show_views_on_posts is enabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    fake_response = {
        "hits": [
            {"path": "/post/hello", "count": 99},
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


async def test_fetch_view_count_returns_none_when_analytics_disabled(session: AsyncSession) -> None:
    """Public view counts are gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False, show_views_on_posts=True)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": [{"path": "/post/hello", "count": 99}]},
    ) as mock_req:
        count = await fetch_view_count(session, "/post/hello")

    assert count is None
    mock_req.assert_not_called()


# ── fetch_* returns None when GoatCounter is down (Issue 5) ───────────────────


async def test_fetch_path_referrers_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_path_referrers returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(session, path_id=7)

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


# ── BreakdownDetailEntry schema classmethod tests ─────────────────────────────


def test_breakdown_detail_entry_from_goatcounter_maps_fields() -> None:
    """BreakdownDetailEntry.from_goatcounter maps name, count, percent correctly."""
    entry = {"name": "Chrome 120", "count": 50, "percent": 62.5}
    result = BreakdownDetailEntry.from_goatcounter(entry)
    assert result.name == "Chrome 120"
    assert result.count == 50
    assert result.percent == 62.5


def test_breakdown_detail_entry_from_goatcounter_defaults_on_missing_keys() -> None:
    """BreakdownDetailEntry.from_goatcounter defaults to Unknown/0 when keys absent."""
    result = BreakdownDetailEntry.from_goatcounter({})
    assert result.name == "Unknown"
    assert result.count == 0
    assert result.percent == 0.0


def test_breakdown_detail_entry_from_goatcounter_maps_blank_name_to_unknown() -> None:
    """BreakdownDetailEntry.from_goatcounter maps blank name to 'Unknown'."""
    assert BreakdownDetailEntry.from_goatcounter({"name": "", "count": 5}).name == "Unknown"
    assert BreakdownDetailEntry.from_goatcounter({"name": "  ", "count": 3}).name == "Unknown"


def test_breakdown_detail_entry_from_goatcounter_coerces_non_int_count_to_zero() -> None:
    """BreakdownDetailEntry.from_goatcounter coerces non-integer count to 0."""
    assert BreakdownDetailEntry.from_goatcounter({"name": "Chrome 120", "count": "N/A"}).count == 0
    assert BreakdownDetailEntry.from_goatcounter({"name": "Chrome 120", "count": None}).count == 0


def test_breakdown_detail_entry_from_goatcounter_computes_percent_when_missing() -> None:
    """BreakdownDetailEntry.from_goatcounter computes percent from total_count when absent."""
    entry = {"name": "Chrome 120", "count": 3}
    result = BreakdownDetailEntry.from_goatcounter(entry, total_count=6)
    assert result.percent == 50.0


# ── fetch_dashboard ────────────────────────────────────────────────────────────


async def test_fetch_dashboard_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """fetch_dashboard is gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"total": 120},
    ) as mock_req:
        result = await fetch_dashboard(session)

    assert result is None
    mock_req.assert_not_called()


async def test_fetch_dashboard_calls_all_goatcounter_endpoints(
    session: AsyncSession,
) -> None:
    """fetch_dashboard calls each GoatCounter endpoint exactly once."""
    hits_response = {
        "hits": [
            {
                "path_id": 1,
                "path": "/post/hello",
                "count": 100,
                "stats": [{"day": "2026-04-01", "daily": 50}, {"day": "2026-04-02", "daily": 50}],
            }
        ]
    }
    breakdown_response = {"stats": [{"name": "Chrome", "count": 80}]}
    toprefs_response = {"stats": [{"name": "hn.algolia.com", "count": 15}]}

    called_endpoints: list[str] = []

    async def fake_stats_request(endpoint: str, params: object = None) -> object:
        called_endpoints.append(endpoint)
        if endpoint == "/api/v0/stats/total":
            return {"total": 200}
        if endpoint == "/api/v0/stats/hits":
            return hits_response
        if endpoint == "/api/v0/stats/toprefs":
            return toprefs_response
        return breakdown_response

    with patch(
        "backend.services.analytics_service._stats_request",
        side_effect=fake_stats_request,
    ):
        result = await fetch_dashboard(session, start="2026-04-01", end="2026-04-02")

    assert result is not None
    assert result.stats.visitors == 200
    assert len(result.paths.paths) == 1
    assert result.paths.paths[0].path == "/post/hello"
    assert len(result.views_over_time.days) == 2
    assert result.views_over_time.days[0].date == "2026-04-01"
    assert result.views_over_time.days[0].views == 50
    assert result.views_over_time.days[1].date == "2026-04-02"
    assert result.views_over_time.days[1].views == 50
    assert len(result.referrers.referrers) == 1
    assert result.referrers.referrers[0].referrer == "hn.algolia.com"

    # All 7 endpoints called exactly once (concurrent — order is not asserted)
    assert sorted(called_endpoints) == sorted(
        [
            "/api/v0/stats/total",
            "/api/v0/stats/hits",
            "/api/v0/stats/browsers",
            "/api/v0/stats/systems",
            "/api/v0/stats/languages",
            "/api/v0/stats/locations",
            "/api/v0/stats/toprefs",
        ]
    )


async def test_fetch_dashboard_hits_fetched_once_for_paths_and_views(
    session: AsyncSession,
) -> None:
    """The /api/v0/stats/hits endpoint is called exactly once for path hits and views-over-time."""
    hits_response = {
        "hits": [
            {
                "path_id": 1,
                "path": "/post/hello",
                "count": 42,
                "stats": [{"day": "2026-04-01", "daily": 42}],
            }
        ]
    }
    hits_call_count = 0

    async def fake_stats_request(endpoint: str, params: object = None) -> object:
        nonlocal hits_call_count
        if endpoint == "/api/v0/stats/hits":
            hits_call_count += 1
            return hits_response
        if endpoint == "/api/v0/stats/total":
            return {"total": 42}
        if endpoint == "/api/v0/stats/toprefs":
            return {"stats": []}
        return {"stats": []}

    with patch(
        "backend.services.analytics_service._stats_request",
        side_effect=fake_stats_request,
    ):
        result = await fetch_dashboard(session)

    assert hits_call_count == 1, "hits endpoint must be fetched only once"
    assert result is not None
    # Both path hits and views-over-time derived from same response
    assert result.paths.paths[0].path == "/post/hello"
    assert result.views_over_time.days[0].date == "2026-04-01"
    assert result.views_over_time.days[0].views == 42


async def test_fetch_dashboard_partial_goatcounter_failure_uses_empty_defaults(
    session: AsyncSession,
) -> None:
    """Individual GoatCounter endpoint failures fall back to empty data, not None."""

    async def fake_stats_request(endpoint: str, params: object = None) -> object | None:
        if endpoint == "/api/v0/stats/total":
            return {"total": 99}
        # All other endpoints return None (simulating GoatCounter rate-limit or error)
        return None

    with patch(
        "backend.services.analytics_service._stats_request",
        side_effect=fake_stats_request,
    ):
        result = await fetch_dashboard(session)

    assert result is not None
    assert result.stats.visitors == 99
    assert result.paths.paths == []
    assert result.views_over_time.days == []
    assert result.browsers.entries == []
    assert result.referrers.referrers == []
