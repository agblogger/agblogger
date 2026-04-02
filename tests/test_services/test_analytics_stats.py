"""Tests for analytics stats proxy methods (Task 5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.base import DurableBase
from backend.schemas.analytics import BreakdownEntry, PathHit, ReferrerEntry, TotalStatsResponse
from backend.services.analytics_service import (
    _build_goatcounter_date_params,
    _normalize_goatcounter_end_date,
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
        result = await fetch_total_stats(session, start="2025-01-01", end="2025-01-31")

    assert result.total_views == 120
    assert result.total_unique == 85


async def test_fetch_total_stats_falls_back_when_unique_missing(session: AsyncSession) -> None:
    """Current GoatCounter builds omit total_unique; fall back to total."""
    fake_response = {"total": 120}

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_total_stats(session)

    assert result.total_views == 120
    assert result.total_unique == 120


async def test_fetch_total_stats_uses_inclusive_bare_end_date(session: AsyncSession) -> None:
    """Bare end dates should be translated to GoatCounter's exclusive next-day bound."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"total": 120},
    ) as mock_stats:
        await fetch_total_stats(session, start="2026-03-26", end="2026-04-02")

    mock_stats.assert_awaited_once_with(
        "/api/v0/stats/total",
        {"start": "2026-03-26", "end": "2026-04-03"},
    )


async def test_fetch_total_stats_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_total_stats returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_total_stats(session)

    assert result is None


async def test_fetch_total_stats_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """Admin stats reads are gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"total": 120, "total_unique": 85},
    ) as mock_req:
        result = await fetch_total_stats(session)

    assert result is None
    mock_req.assert_not_called()


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
        result = await fetch_path_hits(session, start="2025-01-01", end="2025-01-31")

    assert len(result.paths) == 2
    assert result.paths[0].path_id == 1
    assert result.paths[0].path == "/post/hello"
    assert result.paths[0].views == 42
    assert result.paths[0].unique == 30
    assert result.paths[1].path_id == 2
    assert result.paths[1].path == "/post/world"
    assert result.paths[1].views == 17


async def test_fetch_path_hits_accepts_path_id_and_missing_unique(session: AsyncSession) -> None:
    """Current GoatCounter builds use path_id and may omit count_unique."""
    fake_response = {
        "hits": [
            {"path_id": 7, "path": "/post/hello", "count": 42},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_path_hits(session)

    assert len(result.paths) == 1
    assert result.paths[0].path_id == 7
    assert result.paths[0].views == 42
    assert result.paths[0].unique == 42


async def test_fetch_path_hits_uses_inclusive_bare_end_date(session: AsyncSession) -> None:
    """Bare end dates should include the selected calendar day for path hit queries."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": []},
    ) as mock_stats:
        await fetch_path_hits(session, start="2026-03-26", end="2026-04-02")

    mock_stats.assert_awaited_once_with(
        "/api/v0/stats/hits",
        {"start": "2026-03-26", "end": "2026-04-03"},
    )


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
        result = await fetch_path_hits(session)

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
        result = await fetch_path_hits(session)

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
        result = await fetch_path_hits(session)

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
        result = await fetch_path_hits(session)

    assert result is None


async def test_fetch_path_hits_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """Per-path admin stats are gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": []},
    ) as mock_req:
        result = await fetch_path_hits(session)

    assert result is None
    mock_req.assert_not_called()


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


async def test_fetch_breakdown_computes_percent_when_missing(session: AsyncSession) -> None:
    """Current GoatCounter breakdown payloads omit percent; derive it from counts."""
    fake_response = {
        "stats": [
            {"name": "Chrome", "count": 3},
            {"name": "Safari", "count": 2},
            {"name": "Firefox", "count": 1},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_breakdown(session, "browsers")

    assert result.entries[0].percent == 50.0
    assert result.entries[1].percent == pytest.approx(33.3333333333)
    assert result.entries[2].percent == pytest.approx(16.6666666667)


async def test_fetch_breakdown_returns_none_when_unavailable_legacy(
    session: AsyncSession,
) -> None:
    """fetch_breakdown returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown(session, "browsers")

    assert result is None


async def test_fetch_breakdown_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """Breakdown admin stats are gated off when analytics are disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"stats": []},
    ) as mock_req:
        result = await fetch_breakdown(session, "browsers")

    assert result is None
    mock_req.assert_not_called()


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


async def test_fetch_total_stats_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_total_stats returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_total_stats(session)

    assert result is None


async def test_fetch_path_hits_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_path_hits returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_hits(session)

    assert result is None


async def test_fetch_path_referrers_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_path_referrers returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_path_referrers(session, path_id=7)

    assert result is None


async def test_fetch_breakdown_returns_none_when_unavailable(session: AsyncSession) -> None:
    """fetch_breakdown returns None when _stats_request returns None."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown(session, "browsers")

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
    import json

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
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


async def test_stats_request_returns_none_on_non_dict_json() -> None:
    """_stats_request returns None when GoatCounter returns a JSON array instead of object."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [{"unexpected": "array"}]
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


async def test_fetch_view_count_handles_non_numeric_count(session: AsyncSession) -> None:
    """fetch_view_count returns None when GoatCounter returns a non-numeric count value."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    fake_response = {
        "hits": [
            {"path": "/post/hello", "count": "N/A"},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        count = await fetch_view_count(session, "/post/hello")

    assert count is None


async def test_fetch_view_count_returns_none_when_count_is_none_type(
    session: AsyncSession,
) -> None:
    """fetch_view_count returns None when GoatCounter returns count=None (TypeError path)."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=True)

    fake_response = {
        "hits": [
            {"path": "/post/hello", "count": None},
        ]
    }

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        count = await fetch_view_count(session, "/post/hello")

    assert count is None


# ── Issue 1: _stats_request catches OSError (socket-level failures) ───────────


async def test_stats_request_returns_none_on_connection_reset() -> None:
    """_stats_request returns None when a ConnectionResetError is raised."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=ConnectionResetError("Connection reset by peer"))

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


# ── Issue 6: DEBUG logging for missing GoatCounter response keys ──────────────


async def test_fetch_total_stats_logs_debug_on_missing_keys(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """fetch_total_stats logs DEBUG when expected GoatCounter keys are absent."""
    import logging

    with (
        patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value={"unexpected": 999},
        ),
        caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"),
    ):
        result = await fetch_total_stats(session)

    assert result is not None
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    log_messages = " ".join(r.message for r in caplog.records)
    assert "total" in log_messages


async def test_fetch_path_hits_logs_debug_on_missing_keys(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """fetch_path_hits logs DEBUG when expected GoatCounter keys are absent in an entry."""
    import logging

    # Provide a hit entry that is missing expected keys
    with (
        patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value={
                "hits": [
                    {"id": 1, "path": "/post/hello", "unexpected_key": 42},
                ]
            },
        ),
        caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"),
    ):
        result = await fetch_path_hits(session)

    assert result is not None
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    log_messages = " ".join(r.message for r in caplog.records)
    assert "count" in log_messages


# ── Issue 12: Schema factory classmethod tests ────────────────────────────────


def test_total_stats_response_from_goatcounter_maps_fields() -> None:
    """TotalStatsResponse.from_goatcounter maps total and total_unique correctly."""
    data = {"total": 120, "total_unique": 85}
    result = TotalStatsResponse.from_goatcounter(data)
    assert result.total_views == 120
    assert result.total_unique == 85


def test_total_stats_response_from_goatcounter_defaults_on_missing_keys() -> None:
    """TotalStatsResponse.from_goatcounter defaults to 0 when keys are missing."""
    result = TotalStatsResponse.from_goatcounter({})
    assert result.total_views == 0
    assert result.total_unique == 0


def test_total_stats_response_from_goatcounter_falls_back_to_total() -> None:
    """Missing total_unique falls back to total for newer GoatCounter payloads."""
    result = TotalStatsResponse.from_goatcounter({"total": 120})
    assert result.total_views == 120
    assert result.total_unique == 120


def test_normalize_goatcounter_end_date_moves_bare_date_to_next_day() -> None:
    """GoatCounter treats bare end dates as exclusive; move them forward one day."""
    assert _normalize_goatcounter_end_date("2026-04-02") == "2026-04-03"


def test_normalize_goatcounter_end_date_preserves_datetime() -> None:
    """Explicit datetimes should be forwarded unchanged."""
    assert _normalize_goatcounter_end_date("2026-04-02T23:59:59Z") == "2026-04-02T23:59:59Z"


def test_build_goatcounter_date_params_normalizes_end_only() -> None:
    """Date params should keep start unchanged and normalize a bare end date."""
    assert _build_goatcounter_date_params("2026-03-26", "2026-04-02") == {
        "start": "2026-03-26",
        "end": "2026-04-03",
    }


def test_total_stats_response_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TotalStatsResponse.from_goatcounter logs DEBUG when keys are absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        TotalStatsResponse.from_goatcounter({"unexpected": 99})

    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    log_messages = " ".join(r.message for r in caplog.records)
    assert "total" in log_messages


def test_path_hit_from_goatcounter_maps_fields() -> None:
    """PathHit.from_goatcounter maps all expected fields correctly."""
    entry = {"id": 3, "path": "/post/test", "count": 42, "count_unique": 30}
    result = PathHit.from_goatcounter(entry)
    assert result.path_id == 3
    assert result.path == "/post/test"
    assert result.views == 42
    assert result.unique == 30


def test_path_hit_from_goatcounter_accepts_path_id_and_missing_unique() -> None:
    """Missing count_unique falls back to count; path_id aliases id."""
    entry = {"path_id": 3, "path": "/post/test", "count": 42}
    result = PathHit.from_goatcounter(entry)
    assert result.path_id == 3
    assert result.path == "/post/test"
    assert result.views == 42
    assert result.unique == 42


def test_path_hit_from_goatcounter_defaults_on_missing_keys() -> None:
    """PathHit.from_goatcounter defaults numeric fields to 0 when absent."""
    entry = {"id": 1, "path": "/post/test"}
    result = PathHit.from_goatcounter(entry)
    assert result.views == 0
    assert result.unique == 0


def test_path_hit_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PathHit.from_goatcounter logs DEBUG when count or count_unique are absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        PathHit.from_goatcounter({"id": 1, "path": "/post/test"})

    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    log_messages = " ".join(r.message for r in caplog.records)
    assert "count" in log_messages


def test_referrer_entry_from_goatcounter_maps_fields() -> None:
    """ReferrerEntry.from_goatcounter maps name and count correctly."""
    entry = {"name": "https://example.com", "count": 8}
    result = ReferrerEntry.from_goatcounter(entry)
    assert result.referrer == "https://example.com"
    assert result.count == 8


def test_referrer_entry_from_goatcounter_maps_blank_name_to_direct() -> None:
    """Blank GoatCounter referrer names represent direct visits."""
    entry = {"name": "", "count": 5, "ref_scheme": "o"}
    result = ReferrerEntry.from_goatcounter(entry)
    assert result.referrer == "Direct"
    assert result.count == 5


def test_referrer_entry_from_goatcounter_defaults_on_missing_keys() -> None:
    """ReferrerEntry.from_goatcounter defaults to direct and 0 when keys absent."""
    result = ReferrerEntry.from_goatcounter({})
    assert result.referrer == "Direct"
    assert result.count == 0


def test_referrer_entry_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ReferrerEntry.from_goatcounter logs DEBUG when expected keys are absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        ReferrerEntry.from_goatcounter({"unexpected": 1})

    assert any(r.levelno == logging.DEBUG for r in caplog.records)


def test_breakdown_entry_from_goatcounter_maps_fields() -> None:
    """BreakdownEntry.from_goatcounter maps name, count, and percent correctly."""
    entry = {"name": "Chrome", "count": 60, "percent": 60.0}
    result = BreakdownEntry.from_goatcounter(entry)
    assert result.name == "Chrome"
    assert result.count == 60
    assert result.percent == 60.0


def test_breakdown_entry_from_goatcounter_computes_percent_when_missing() -> None:
    """Missing percent falls back to a share derived from total_count."""
    entry = {"name": "Chrome", "count": 3}
    result = BreakdownEntry.from_goatcounter(entry, total_count=6)
    assert result.name == "Chrome"
    assert result.count == 3
    assert result.percent == 50.0


def test_breakdown_entry_from_goatcounter_defaults_on_missing_keys() -> None:
    """BreakdownEntry.from_goatcounter defaults to zeros when keys are absent."""
    result = BreakdownEntry.from_goatcounter({})
    assert result.name == ""
    assert result.count == 0
    assert result.percent == 0.0


def test_breakdown_entry_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BreakdownEntry.from_goatcounter logs DEBUG when expected keys are absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        BreakdownEntry.from_goatcounter({"unexpected": 1})

    assert any(r.levelno == logging.DEBUG for r in caplog.records)
