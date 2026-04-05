"""Analytics service: settings, hit recording, stats proxy, and background tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx
from crawlerdetect import CrawlerDetect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.analytics import AnalyticsSettings
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    BreakdownCategory,
    BreakdownDetailCategory,
    BreakdownDetailEntry,
    BreakdownDetailResponse,
    BreakdownEntry,
    BreakdownResponse,
    DailyViewCount,
    DashboardResponse,
    ExportCreateResponse,
    ExportStatusResponse,
    PathHit,
    PathHitsResponse,
    PathReferrersResponse,
    ReferrerEntry,
    SiteReferrersResponse,
    TotalStatsResponse,
    ViewsOverTimeResponse,
)
from backend.utils.datetime import parse_datetime
from backend.utils.goatcounter import normalize_goatcounter_site_host

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.models.user import AdminUser

logger = logging.getLogger(__name__)

# ── GoatCounter connection constants ───────────────────────────────────────────

# Internal Docker network address; matches the goatcounter service in docker-compose.yml
GOATCOUNTER_URL = "http://goatcounter:8080"
# GoatCounter provisions the site under this host, so requests must present it
# explicitly even when they connect to the service by its Docker DNS name.
GOATCOUNTER_SITE_HOST = (
    normalize_goatcounter_site_host(os.getenv("GOATCOUNTER_SITE_HOST", "stats.internal"))
    or "stats.internal"
)
GOATCOUNTER_AUTH_FILE = "/data/goatcounter-token/token"
_HIT_TIMEOUT = 2.0
_STATS_TIMEOUT = 5.0
# OSError covers socket-level failures that may not be wrapped by httpx.
_HIT_ERRORS = (httpx.HTTPError, OSError)
_STATS_ERRORS = (httpx.HTTPError, httpx.InvalidURL, json.JSONDecodeError, OSError)
_COUNT_PARSE_ERRORS = (TypeError, ValueError)
_MAX_BACKGROUND_TASKS = 64

# ── Module-level singletons ────────────────────────────────────────────────────

_crawler_detect = CrawlerDetect()
_http_client: httpx.AsyncClient | None = None
_goatcounter_token: str | None = None
_token_warning_issued: bool = False

# Strong references to fire-and-forget analytics tasks, preventing GC before completion.
_background_tasks: set[asyncio.Task[None]] = set()


def _analytics_enabled_default() -> bool:
    """Return the deployment default for analytics when no row exists yet."""
    raw = os.getenv("ANALYTICS_ENABLED_DEFAULT", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _effective_analytics_enabled(persisted_enabled: bool) -> bool:
    """Return the effective analytics state for the current deployment."""
    return _analytics_enabled_default() and persisted_enabled


def _settings_response(
    *,
    analytics_enabled: bool,
    show_views_on_posts: bool,
) -> AnalyticsSettingsResponse:
    """Build the API response for analytics settings."""
    return AnalyticsSettingsResponse(
        analytics_enabled=_effective_analytics_enabled(analytics_enabled),
        show_views_on_posts=show_views_on_posts,
    )


def _goatcounter_headers(token: str) -> dict[str, str]:
    """Return headers required for authenticated GoatCounter requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Host": GOATCOUNTER_SITE_HOST,
    }


def _normalize_goatcounter_end_date(end: str) -> str:
    """Convert a bare YYYY-MM-DD end date to GoatCounter's exclusive upper bound."""
    if "T" in end or " " in end.strip():
        return end
    try:
        return (parse_datetime(end) + timedelta(days=1)).date().isoformat()
    except ValueError:
        logger.warning(
            "Invalid analytics end date %r; passing through unchanged",
            end,
            exc_info=True,
        )
        return end


def _build_goatcounter_date_params(
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    """Build GoatCounter date params, treating bare end dates as inclusive."""
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = _normalize_goatcounter_end_date(end)
    return params


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it lazily on first call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    return _http_client


def _load_token() -> str | None:
    """Load the GoatCounter API token from disk.

    Returns the token string on success, or None if the file does not exist
    yet. Logs a warning on the first miss and subsequent misses at DEBUG
    level. The file is re-read on every call so token-sidecar reprovisioning
    is picked up without an application restart.
    """
    global _goatcounter_token, _token_warning_issued
    try:
        with open(GOATCOUNTER_AUTH_FILE) as fh:
            token = fh.read().strip()
        if token:
            _goatcounter_token = token
            _token_warning_issued = False
            return _goatcounter_token
        _goatcounter_token = None
        logger.warning("GoatCounter auth file is empty: %s", GOATCOUNTER_AUTH_FILE)
        return None
    except FileNotFoundError:
        _goatcounter_token = None
        if not _token_warning_issued:
            _token_warning_issued = True
            logger.warning(
                "GoatCounter auth file not yet available at %s"
                " — analytics disabled until file appears",
                GOATCOUNTER_AUTH_FILE,
            )
        else:
            logger.debug(
                "GoatCounter auth file still not available at %s",
                GOATCOUNTER_AUTH_FILE,
            )
        return None
    except OSError as exc:
        _goatcounter_token = None
        logger.error(
            "Cannot read GoatCounter auth file %s: %s",
            GOATCOUNTER_AUTH_FILE,
            exc,
            exc_info=True,
        )
        return None


# ── Settings management ────────────────────────────────────────────────────────


async def get_analytics_settings(session: AsyncSession) -> AnalyticsSettingsResponse:
    """Return current analytics settings, falling back to defaults if no row exists.

    Returns an AnalyticsSettingsResponse with defaults when no row has been
    persisted yet. ``analytics_enabled`` follows the deployment-level
    ``ANALYTICS_ENABLED_DEFAULT`` environment flag; ``show_views_on_posts``
    remains disabled by default. The returned response is not backed by a
    persisted row; callers that need a persistent row should use
    update_analytics_settings instead.
    """
    result = await session.execute(select(AnalyticsSettings).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        return _settings_response(
            analytics_enabled=_analytics_enabled_default(),
            show_views_on_posts=False,
        )
    return _settings_response(
        analytics_enabled=row.analytics_enabled,
        show_views_on_posts=row.show_views_on_posts,
    )


async def update_analytics_settings(
    session: AsyncSession,
    *,
    analytics_enabled: bool | None = None,
    show_views_on_posts: bool | None = None,
) -> AnalyticsSettingsResponse:
    """Create or update analytics settings, applying only the provided fields.

    On first call, creates the singleton settings row. On subsequent calls,
    updates only the fields that are not None, leaving other fields unchanged.

    Handles the race condition where a concurrent request inserts the singleton
    row between our SELECT and INSERT by catching IntegrityError and retrying
    with an UPDATE on the existing row.
    """
    result = await session.execute(select(AnalyticsSettings).limit(1))
    row = result.scalar_one_or_none()

    if row is None:
        row = AnalyticsSettings(
            analytics_enabled=(
                _analytics_enabled_default() if analytics_enabled is None else analytics_enabled
            ),
            show_views_on_posts=False if show_views_on_posts is None else show_views_on_posts,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(AnalyticsSettings).limit(1))
            row = result.scalar_one()
            if analytics_enabled is not None:
                row.analytics_enabled = analytics_enabled
            if show_views_on_posts is not None:
                row.show_views_on_posts = show_views_on_posts
    else:
        if analytics_enabled is not None:
            row.analytics_enabled = analytics_enabled
        if show_views_on_posts is not None:
            row.show_views_on_posts = show_views_on_posts

    await session.commit()
    await session.refresh(row)
    return _settings_response(
        analytics_enabled=row.analytics_enabled,
        show_views_on_posts=row.show_views_on_posts,
    )


# ── Hit recording ──────────────────────────────────────────────────────────────


async def record_hit(
    *,
    session: AsyncSession,
    path: str,
    client_ip: str,
    user_agent: str,
    user: AdminUser | None,
) -> None:
    """Record a page view hit to GoatCounter.

    Network and HTTP errors are logged but never propagated; programming bugs
    (TypeError, AttributeError, etc.) are allowed to propagate so they remain
    visible in the caller's error handling.

    Skips recording when:
    - The requester is authenticated (i.e., the admin).
    - The User-Agent is identified as a bot/crawler.
    - Analytics are disabled in settings.
    - The GoatCounter token is not yet available.
    """
    # Skip authenticated admin — admin browsing should not inflate counts.
    if user is not None:
        return

    if _crawler_detect.is_crawler(user_agent):
        return

    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return

    token = _load_token()
    if token is None:
        return

    try:
        client = _get_http_client()
        response = await client.post(
            f"{GOATCOUNTER_URL}/api/v0/count",
            json={
                "hits": [
                    {
                        "path": path,
                        "ip": client_ip,
                        "user_agent": user_agent,
                    }
                ]
            },
            headers=_goatcounter_headers(token),
            timeout=_HIT_TIMEOUT,
        )
        response.raise_for_status()
    except _HIT_ERRORS:
        logger.warning("Failed to record analytics hit for path %r", path, exc_info=True)


# ── Stats proxy ────────────────────────────────────────────────────────────────


async def _stats_request(
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Authenticated GET to GoatCounter; returns parsed JSON or None on expected errors.

    Network/HTTP errors and JSON decode errors are caught and logged.
    Programming bugs (TypeError, AttributeError, etc.) propagate to the caller.
    """
    token = _load_token()
    if token is None:
        return None
    try:
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}{endpoint}",
            params=params,
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.warning(
                "GoatCounter returned non-object JSON for %r: %s",
                endpoint,
                type(data).__name__,
            )
            return None
        return data
    except _STATS_ERRORS:
        logger.warning(
            "GoatCounter stats request to %r (params=%r) failed",
            endpoint,
            params,
            exc_info=True,
        )
        return None


# ── Background hit helper ─────────────────────────────────────────────────────


def fire_background_hit(
    request: Request,
    session_factory: async_sessionmaker[AsyncSession],
    path: str,
    user: AdminUser | None,
) -> None:
    """Schedule a fire-and-forget analytics hit recording task.

    Extracts client IP and user agent from the request, then creates an asyncio
    task that opens an independent database session and calls record_hit. Any
    failure in the background task is logged but never propagated.
    """
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    user_agent = request.headers.get("user-agent", "")

    if len(_background_tasks) >= _MAX_BACKGROUND_TASKS:
        logger.warning(
            "Dropping analytics hit for %r because the background task limit (%d) was reached",
            path,
            _MAX_BACKGROUND_TASKS,
        )
        return

    async def _do_hit() -> None:
        try:
            async with session_factory() as session:
                await record_hit(
                    session=session,
                    path=path,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    user=user,
                )
        except Exception:
            logger.warning("Background analytics hit failed for %r", path, exc_info=True)

    task = asyncio.create_task(_do_hit())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _parse_hits_data(data: dict[str, Any]) -> tuple[PathHitsResponse, ViewsOverTimeResponse]:
    """Parse a GoatCounter /api/v0/stats/hits response into path hits and views-over-time.

    Both are derived from the same response to avoid a duplicate GoatCounter request.
    """
    paths: list[PathHit] = []
    day_totals: dict[str, int] = {}
    for entry in data.get("hits", []):
        if not isinstance(entry, dict):
            continue
        path_id = entry.get("path_id", entry.get("id"))
        path = entry.get("path", "")
        if path_id and isinstance(path_id, int) and path_id >= 1 and path:
            paths.append(PathHit.from_goatcounter(entry))
        for stat_block in entry.get("stats", []):
            if not isinstance(stat_block, dict):
                continue
            day = stat_block.get("day", "")
            if not day:
                continue
            daily_count = stat_block.get("daily", 0)
            if isinstance(daily_count, int):
                day_totals[day] = day_totals.get(day, 0) + daily_count
    days = [DailyViewCount(date=d, views=v) for d, v in sorted(day_totals.items())]
    return PathHitsResponse(paths=paths), ViewsOverTimeResponse(days=days)


def _parse_breakdown_data(data: dict[str, Any], category: BreakdownCategory) -> BreakdownResponse:
    """Parse a GoatCounter /api/v0/stats/{category} response into a BreakdownResponse."""
    stats = data.get("stats", [])
    total_count = sum(
        entry.get("count", 0)
        for entry in stats
        if isinstance(entry, dict) and isinstance(entry.get("count", 0), int)
    )
    entries = [
        BreakdownEntry.from_goatcounter(entry, total_count=total_count)
        for entry in stats
        if isinstance(entry, dict)
    ]
    return BreakdownResponse(category=category, entries=entries)


def _parse_referrers_data(data: dict[str, Any]) -> SiteReferrersResponse:
    """Parse a GoatCounter /api/v0/stats/toprefs response into a SiteReferrersResponse."""
    referrers = sorted(
        [
            ReferrerEntry.from_goatcounter(entry)
            for entry in data.get("stats", [])
            if isinstance(entry, dict)
        ],
        key=lambda r: r.count,
        reverse=True,
    )
    return SiteReferrersResponse(referrers=referrers)


async def fetch_path_referrers(
    session: AsyncSession,
    path_id: int,
) -> PathReferrersResponse | None:
    """Proxy GoatCounter referrer breakdown for a path; returns None when unavailable."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    data = await _stats_request(f"/api/v0/stats/hits/{path_id}")
    if data is None:
        return None
    referrers = [ReferrerEntry.from_goatcounter(entry) for entry in data.get("refs", [])]
    return PathReferrersResponse(path_id=path_id, referrers=referrers)


async def fetch_breakdown_detail(
    session: AsyncSession,
    category: BreakdownDetailCategory,
    entry_id: str,
) -> BreakdownDetailResponse | None:
    """Proxy GoatCounter version drill-down for a breakdown entry.

    Returns None when analytics is disabled or GoatCounter is unavailable.
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    data = await _stats_request(f"/api/v0/stats/{category}/{entry_id}")
    if data is None:
        return None

    stats = data.get("stats", [])
    total_count = sum(
        e.get("count", 0)
        for e in stats
        if isinstance(e, dict) and isinstance(e.get("count", 0), int)
    )
    entries = [
        BreakdownDetailEntry.from_goatcounter(e, total_count=total_count)
        for e in stats
        if isinstance(e, dict)
    ]
    return BreakdownDetailResponse(category=category, entry_id=entry_id, entries=entries)


async def fetch_view_count(
    session: AsyncSession,
    path: str,
) -> int | None:
    """Return the public view count for a path, or None if view counts are disabled.

    Checks the show_views_on_posts setting first; returns None immediately when
    disabled.  Returns None when GoatCounter is unavailable rather than
    raising.
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled or not settings.show_views_on_posts:
        return None

    data = await _stats_request("/api/v0/stats/hits", {"filter": path})
    if data is None:
        return None
    hits = data.get("hits", [])
    for entry in hits:
        if entry.get("path") == path:
            try:
                return int(entry.get("count", 0))
            except _COUNT_PARSE_ERRORS:
                logger.warning("Unexpected count value in GoatCounter response for path %r", path)
                return None
    return 0


async def fetch_dashboard(
    session: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> DashboardResponse | None:
    """Fetch all dashboard data from GoatCounter concurrently.

    Fires 9 GoatCounter requests in parallel via asyncio.gather. The
    /api/v0/stats/hits response is reused for both path hits and
    views-over-time, eliminating a duplicate call. Individual endpoint
    failures fall back to empty/zero data so a partial GoatCounter outage
    does not block the entire dashboard.

    Returns None when analytics is disabled.
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    params = _build_goatcounter_date_params(start, end) or None

    (
        total_data,
        hits_data,
        browsers_data,
        systems_data,
        languages_data,
        locations_data,
        sizes_data,
        campaigns_data,
        referrers_data,
    ) = await asyncio.gather(
        _stats_request("/api/v0/stats/total", params),
        _stats_request("/api/v0/stats/hits", params),
        _stats_request("/api/v0/stats/browsers", params),
        _stats_request("/api/v0/stats/systems", params),
        _stats_request("/api/v0/stats/languages", params),
        _stats_request("/api/v0/stats/locations", params),
        _stats_request("/api/v0/stats/sizes", params),
        _stats_request("/api/v0/stats/campaigns", params),
        _stats_request("/api/v0/stats/toprefs", params),
    )

    stats = (
        TotalStatsResponse.from_goatcounter(total_data)
        if total_data is not None
        else TotalStatsResponse(visitors=0)
    )
    paths, views_over_time = (
        _parse_hits_data(hits_data)
        if hits_data is not None
        else (PathHitsResponse(paths=[]), ViewsOverTimeResponse(days=[]))
    )

    def _bd(data: dict[str, Any] | None, category: BreakdownCategory) -> BreakdownResponse:
        return (
            _parse_breakdown_data(data, category)
            if data is not None
            else BreakdownResponse(category=category, entries=[])
        )

    return DashboardResponse(
        stats=stats,
        paths=paths,
        views_over_time=views_over_time,
        browsers=_bd(browsers_data, "browsers"),
        operating_systems=_bd(systems_data, "systems"),
        languages=_bd(languages_data, "languages"),
        locations=_bd(locations_data, "locations"),
        sizes=_bd(sizes_data, "sizes"),
        campaigns=_bd(campaigns_data, "campaigns"),
        referrers=(
            _parse_referrers_data(referrers_data)
            if referrers_data is not None
            else SiteReferrersResponse(referrers=[])
        ),
    )


async def create_export(
    session: AsyncSession,
) -> ExportCreateResponse | None:
    """Create a CSV export job on GoatCounter."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.post(
            f"{GOATCOUNTER_URL}/api/v0/export",
            json={},
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        export_id = data.get("id")
        if not isinstance(export_id, int) or export_id <= 0:
            logger.error(
                "GoatCounter export creation response missing valid 'id' field: %r",
                data,
            )
            return None
        return ExportCreateResponse(id=export_id)
    except _STATS_ERRORS:
        logger.warning("Failed to create GoatCounter export", exc_info=True)
        return None


async def get_export_status(
    session: AsyncSession,
    export_id: int,
) -> ExportStatusResponse | None:
    """Check the status of a GoatCounter CSV export job."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}/api/v0/export/{export_id}",
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        response_id = data.get("id")
        if not isinstance(response_id, int):
            logger.error(
                "GoatCounter export status response missing valid 'id' field for export %d: %r",
                export_id,
                data,
            )
            return None
        return ExportStatusResponse(
            id=response_id,
            finished=data.get("finished_at") is not None,
        )
    except _STATS_ERRORS:
        logger.warning("Failed to check GoatCounter export %d status", export_id, exc_info=True)
        return None


async def download_export(
    session: AsyncSession,
    export_id: int,
) -> bytes | None:
    """Download a completed GoatCounter CSV export."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}/api/v0/export/{export_id}/download",
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        content = response.content
        if not content:
            logger.warning("GoatCounter returned empty body for export %d download", export_id)
            return None
        return content
    except _STATS_ERRORS:
        logger.warning("Failed to download GoatCounter export %d", export_id, exc_info=True)
        return None


async def close_analytics_client() -> None:
    """Close the shared httpx client, releasing connections.

    Drains pending background tasks (with a short timeout) before closing
    the client to avoid noisy ClosedPoolError warnings from in-flight hits.
    """
    global _http_client
    if _background_tasks:
        await asyncio.wait(_background_tasks, timeout=3.0)
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
