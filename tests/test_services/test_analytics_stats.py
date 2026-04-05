"""Tests for analytics stats proxy methods (Task 5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.base import DurableBase
from backend.schemas.analytics import (
    BreakdownDetailEntry,
    BreakdownEntry,
    PathHit,
    ReferrerEntry,
    TotalStatsResponse,
)
from backend.services.analytics_service import (
    _build_goatcounter_date_params,
    _normalize_goatcounter_end_date,
    _stats_request,
    fetch_breakdown_detail,
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


# ── CSV export service functions ───────────────────────────────────────────────


async def test_create_export_returns_id(session: AsyncSession) -> None:
    """create_export returns the export job id from GoatCounter."""
    from backend.services.analytics_service import create_export

    fake_post_response = MagicMock()
    fake_post_response.status_code = 202
    fake_post_response.json.return_value = {"id": 42}
    fake_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_post_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await create_export(session)

    assert result is not None
    assert result.id == 42


async def test_create_export_returns_none_when_disabled(session: AsyncSession) -> None:
    """create_export returns None when analytics is disabled."""
    from backend.services.analytics_service import create_export, update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)
    result = await create_export(session)
    assert result is None


async def test_get_export_status_finished(session: AsyncSession) -> None:
    """get_export_status returns finished=True when finished_at is set."""
    from backend.services.analytics_service import get_export_status

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"id": 42, "finished_at": "2026-04-05T12:00:00Z"}
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await get_export_status(session, 42)

    assert result is not None
    assert result.finished is True


async def test_get_export_status_not_finished(session: AsyncSession) -> None:
    """get_export_status returns finished=False when finished_at is null."""
    from backend.services.analytics_service import get_export_status

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"id": 42, "finished_at": None}
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await get_export_status(session, 42)

    assert result is not None
    assert result.finished is False


async def test_download_export_returns_bytes(session: AsyncSession) -> None:
    """download_export returns raw bytes from GoatCounter."""
    from backend.services.analytics_service import download_export

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = b"csv-data-here"
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await download_export(session, 42)

    assert result == b"csv-data-here"


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


# ── Issue 12: Schema factory classmethod tests ────────────────────────────────


def test_total_stats_response_from_goatcounter_maps_fields() -> None:
    """TotalStatsResponse.from_goatcounter maps GoatCounter's 'total' field to 'visitors'."""
    data = {"total": 120}
    result = TotalStatsResponse.from_goatcounter(data)
    assert result.visitors == 120


def test_total_stats_response_from_goatcounter_defaults_on_missing_keys() -> None:
    """TotalStatsResponse.from_goatcounter defaults to 0 when keys are missing."""
    result = TotalStatsResponse.from_goatcounter({})
    assert result.visitors == 0


def test_total_stats_response_from_goatcounter_ignores_unknown_keys() -> None:
    """Extra GoatCounter fields are silently ignored."""
    result = TotalStatsResponse.from_goatcounter({"total": 120, "total_events": 10})
    assert result.visitors == 120


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
    """PathHit.from_goatcounter maps GoatCounter's path_id, path, count fields."""
    entry = {"path_id": 3, "path": "/post/test", "count": 42}
    result = PathHit.from_goatcounter(entry)
    assert result.path_id == 3
    assert result.path == "/post/test"
    assert result.views == 42


def test_path_hit_from_goatcounter_accepts_legacy_id_field() -> None:
    """GoatCounter v2 uses 'path_id', but 'id' is accepted as fallback."""
    entry = {"id": 3, "path": "/post/test", "count": 42}
    result = PathHit.from_goatcounter(entry)
    assert result.path_id == 3
    assert result.path == "/post/test"
    assert result.views == 42


def test_path_hit_from_goatcounter_prefers_path_id_over_id() -> None:
    """When both path_id and id are present, path_id takes precedence."""
    entry = {"path_id": 5, "id": 3, "path": "/post/test", "count": 10}
    result = PathHit.from_goatcounter(entry)
    assert result.path_id == 5


def test_path_hit_from_goatcounter_defaults_on_missing_keys() -> None:
    """PathHit.from_goatcounter defaults numeric fields to 0 when absent."""
    entry = {"path_id": 1, "path": "/post/test"}
    result = PathHit.from_goatcounter(entry)
    assert result.views == 0


def test_path_hit_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PathHit.from_goatcounter logs DEBUG when count is absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        PathHit.from_goatcounter({"path_id": 1, "path": "/post/test"})

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
    """BreakdownEntry.from_goatcounter defaults to "Unknown" name and zeros when keys are absent."""
    result = BreakdownEntry.from_goatcounter({})
    assert result.name == "Unknown"
    assert result.count == 0
    assert result.percent == 0.0


def test_breakdown_entry_from_goatcounter_maps_blank_name_to_unknown() -> None:
    """Empty or whitespace-only browser/OS names are labelled 'Unknown'."""
    assert BreakdownEntry.from_goatcounter({"name": "", "count": 5}).name == "Unknown"
    assert BreakdownEntry.from_goatcounter({"name": "  ", "count": 3}).name == "Unknown"
    assert BreakdownEntry.from_goatcounter({"name": None, "count": 1}).name == "Unknown"


def test_breakdown_entry_from_goatcounter_coerces_non_int_count_to_zero() -> None:
    """Non-integer count values are treated as 0 to prevent TypeError in percent math."""
    assert BreakdownEntry.from_goatcounter({"name": "Chrome", "count": "N/A"}).count == 0
    assert BreakdownEntry.from_goatcounter({"name": "Chrome", "count": None}).count == 0
    assert BreakdownEntry.from_goatcounter({"name": "Chrome", "count": 3.5}).count == 0


def test_breakdown_entry_from_goatcounter_maps_non_string_name_to_unknown() -> None:
    """Non-string name types (int, bool) are labelled 'Unknown'."""
    assert BreakdownEntry.from_goatcounter({"name": 0, "count": 1}).name == "Unknown"
    assert BreakdownEntry.from_goatcounter({"name": False, "count": 1}).name == "Unknown"


def test_breakdown_entry_from_goatcounter_logs_debug_on_missing_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BreakdownEntry.from_goatcounter logs DEBUG when expected keys are absent."""
    with caplog.at_level(logging.DEBUG, logger="backend.schemas.analytics"):
        BreakdownEntry.from_goatcounter({"unexpected": 1})

    assert any(r.levelno == logging.DEBUG for r in caplog.records)


# ── fetch_breakdown_detail ─────────────────────────────────────────────────────


async def test_fetch_breakdown_detail_returns_versions(session: AsyncSession) -> None:
    """fetch_breakdown_detail returns version entries for a browser/OS."""
    fake_response = {
        "stats": [
            {"name": "Chrome 120", "count": 50},
            {"name": "Chrome 119", "count": 30},
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_breakdown_detail(session, "browsers", "3")

    assert result is not None
    assert result.category == "browsers"
    assert result.entry_id == "3"
    assert len(result.entries) == 2
    assert result.entries[0].name == "Chrome 120"
    assert result.entries[0].count == 50


async def test_fetch_breakdown_detail_returns_none_when_unavailable(
    session: AsyncSession,
) -> None:
    """fetch_breakdown_detail returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown_detail(session, "browsers", "3")

    assert result is None


async def test_fetch_breakdown_detail_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """fetch_breakdown_detail returns None when analytics is disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)

    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"stats": []},
    ) as mock_req:
        result = await fetch_breakdown_detail(session, "browsers", "3")

    assert result is None
    mock_req.assert_not_called()


# ── get_export_status and download_export disabled-gating ─────────────────────


async def test_get_export_status_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """get_export_status returns None when analytics is disabled."""
    from backend.services.analytics_service import get_export_status, update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)
    result = await get_export_status(session, 42)
    assert result is None


async def test_download_export_returns_none_when_analytics_disabled(
    session: AsyncSession,
) -> None:
    """download_export returns None when analytics is disabled."""
    from backend.services.analytics_service import download_export, update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)
    result = await download_export(session, 42)
    assert result is None


# ── Issue 12 (service): Validate export ID in create_export ───────────────────


async def test_create_export_returns_none_when_id_missing(session: AsyncSession) -> None:
    """create_export returns None when GoatCounter response missing valid id."""
    from backend.services.analytics_service import create_export

    fake_post_response = MagicMock()
    fake_post_response.status_code = 202
    fake_post_response.json.return_value = {}  # No "id" key
    fake_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_post_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await create_export(session)

    assert result is None


async def test_create_export_returns_none_when_id_is_zero(session: AsyncSession) -> None:
    """create_export returns None when GoatCounter returns id=0."""
    from backend.services.analytics_service import create_export

    fake_post_response = MagicMock()
    fake_post_response.status_code = 202
    fake_post_response.json.return_value = {"id": 0}
    fake_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_post_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await create_export(session)

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

    # All 9 endpoints called exactly once (concurrent — order is not asserted)
    assert sorted(called_endpoints) == sorted(
        [
            "/api/v0/stats/total",
            "/api/v0/stats/hits",
            "/api/v0/stats/browsers",
            "/api/v0/stats/systems",
            "/api/v0/stats/languages",
            "/api/v0/stats/locations",
            "/api/v0/stats/sizes",
            "/api/v0/stats/campaigns",
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
