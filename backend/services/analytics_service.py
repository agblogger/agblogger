"""Analytics service: settings management, hit recording, and stats proxy."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

import httpx
from crawlerdetect import CrawlerDetect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.analytics import AnalyticsSettings
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    BreakdownCategory,
    BreakdownEntry,
    BreakdownResponse,
    PathHit,
    PathHitsResponse,
    PathReferrersResponse,
    ReferrerEntry,
    TotalStatsResponse,
)

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.models.user import User

logger = logging.getLogger(__name__)

# ── GoatCounter connection constants ───────────────────────────────────────────

# Internal Docker network address; matches the goatcounter service in docker-compose.yml
GOATCOUNTER_URL = "http://goatcounter:8080"
GOATCOUNTER_AUTH_FILE = "/data/goatcounter/token"
_HIT_TIMEOUT = 2.0
_STATS_TIMEOUT = 5.0
_HIT_ERRORS = (httpx.HTTPError, OSError)
_STATS_ERRORS = (httpx.HTTPError, httpx.InvalidURL, ValueError)

# ── Module-level singletons ────────────────────────────────────────────────────

_crawler_detect = CrawlerDetect()
_http_client: httpx.AsyncClient | None = None
_goatcounter_token: str | None = None
_token_warning_issued: bool = False

# Strong references to fire-and-forget analytics tasks, preventing GC before completion.
_background_tasks: set[asyncio.Task[None]] = set()


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it lazily on first call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    return _http_client


def _load_token() -> str | None:
    """Load the GoatCounter API token from disk, caching the result.

    Returns the token string on success, or None if the file does not exist
    yet.  Logs a warning on the first miss and subsequent misses at DEBUG
    level.
    """
    global _goatcounter_token, _token_warning_issued
    if _goatcounter_token is not None:
        return _goatcounter_token
    try:
        with open(GOATCOUNTER_AUTH_FILE) as fh:
            token = fh.read().strip()
        if token:
            _goatcounter_token = token
            return _goatcounter_token
        logger.warning("GoatCounter token file is empty: %s", GOATCOUNTER_AUTH_FILE)
        return None
    except FileNotFoundError:
        if not _token_warning_issued:
            _token_warning_issued = True
            logger.warning(
                "GoatCounter token not yet available at %s"
                " — analytics disabled until token appears",
                GOATCOUNTER_AUTH_FILE,
            )
        else:
            logger.debug(
                "GoatCounter token still not available at %s",
                GOATCOUNTER_AUTH_FILE,
            )
        return None
    except OSError as exc:
        logger.error(
            "Cannot read GoatCounter token file %s: %s",
            GOATCOUNTER_AUTH_FILE,
            exc,
        )
        return None


# ── Settings management ────────────────────────────────────────────────────────


async def get_analytics_settings(session: AsyncSession) -> AnalyticsSettingsResponse:
    """Return current analytics settings, falling back to defaults if no row exists.

    Returns an AnalyticsSettingsResponse with defaults (analytics_enabled=True,
    show_views_on_posts=False) when no row has been persisted yet. The returned
    response is not backed by a persisted row; callers that need a persistent row
    should use update_analytics_settings instead.
    """
    result = await session.execute(select(AnalyticsSettings).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        return AnalyticsSettingsResponse(analytics_enabled=True, show_views_on_posts=False)
    return AnalyticsSettingsResponse(
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
            analytics_enabled=True if analytics_enabled is None else analytics_enabled,
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
    return AnalyticsSettingsResponse(
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
    user: User | None,
) -> None:
    """Record a page view hit to GoatCounter.

    Network and HTTP errors are logged but never propagated; programming bugs
    (TypeError, AttributeError, etc.) are allowed to propagate so they remain
    visible in the caller's error handling.

    Skips recording when:
    - The request carries a valid authenticated user session.
    - The User-Agent is identified as a bot/crawler.
    - Analytics are disabled in settings.
    - The GoatCounter token is not yet available.
    """
    # Skip authenticated users — admin/editor browsing should not inflate counts.
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
                        "ua": user_agent,
                    }
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
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
            headers={"Authorization": f"Bearer {token}"},
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())
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
    user: User | None,
) -> None:
    """Schedule a fire-and-forget analytics hit recording task.

    Extracts client IP and user agent from the request, then creates an asyncio
    task that opens an independent database session and calls record_hit. Any
    failure in the background task is logged but never propagated.
    """
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    user_agent = request.headers.get("user-agent", "")

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


async def fetch_total_stats(
    start: str | None = None,
    end: str | None = None,
) -> TotalStatsResponse | None:
    """Proxy GoatCounter total stats; returns None when unavailable."""
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request("/api/v0/stats/total", params or None)
    if data is None:
        return None
    return TotalStatsResponse(
        total_views=data.get("total", 0),
        total_unique=data.get("total_unique", 0),
    )


async def fetch_path_hits(
    start: str | None = None,
    end: str | None = None,
) -> PathHitsResponse | None:
    """Proxy GoatCounter per-path hit counts; returns None when unavailable."""
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request("/api/v0/stats/hits", params or None)
    if data is None:
        return None
    paths: list[PathHit] = []
    for entry in data.get("hits", []):
        path_id = entry.get("id")
        if not path_id or path_id < 1:
            continue
        path = entry.get("path", "")
        if not path:
            continue
        paths.append(
            PathHit(
                path_id=path_id,
                path=path,
                views=entry.get("count", 0),
                unique=entry.get("count_unique", 0),
            )
        )
    return PathHitsResponse(paths=paths)


async def fetch_path_referrers(
    path_id: int,
) -> PathReferrersResponse | None:
    """Proxy GoatCounter referrer breakdown for a path; returns None when unavailable."""
    data = await _stats_request(f"/api/v0/stats/hits/{path_id}/referrers")
    if data is None:
        return None
    referrers = [
        ReferrerEntry(
            referrer=entry.get("name", ""),
            count=entry.get("count", 0),
        )
        for entry in data.get("referrers", [])
    ]
    return PathReferrersResponse(path_id=path_id, referrers=referrers)


async def fetch_breakdown(
    category: BreakdownCategory,
    start: str | None = None,
    end: str | None = None,
) -> BreakdownResponse | None:
    """Proxy GoatCounter category breakdown (browsers, systems, locations, etc.).

    Returns None when GoatCounter is unavailable.
    """
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request(f"/api/v0/stats/{category}", params or None)
    if data is None:
        return None
    entries = [
        BreakdownEntry(
            name=entry.get("name", ""),
            count=entry.get("count", 0),
            percent=entry.get("percent", 0.0),
        )
        for entry in data.get("stats", [])
    ]
    return BreakdownResponse(category=category, entries=entries)


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
    if not settings.show_views_on_posts:
        return None

    data = await _stats_request("/api/v0/stats/hits", {"filter": path})
    if data is None:
        return None
    hits = data.get("hits", [])
    for entry in hits:
        if entry.get("path") == path:
            return int(entry.get("count", 0))
    return 0


async def close_analytics_client() -> None:
    """Close the shared httpx client, releasing connections."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
