"""Analytics service: settings management, hit recording, and stats proxy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from crawlerdetect import CrawlerDetect
from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    BreakdownEntry,
    BreakdownResponse,
    PathHit,
    PathHitsResponse,
    PathReferrersResponse,
    ReferrerEntry,
    TotalStatsResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.models.user import User

logger = logging.getLogger(__name__)

# ── GoatCounter connection constants ───────────────────────────────────────────

GOATCOUNTER_URL = "http://goatcounter:8080"
GOATCOUNTER_AUTH_FILE = "/data/goatcounter/token"
_HIT_TIMEOUT = 2.0
_STATS_TIMEOUT = 5.0

# ── Module-level singletons ────────────────────────────────────────────────────

_crawler_detect = CrawlerDetect()
_http_client: httpx.AsyncClient | None = None
_goatcounter_token: str | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it lazily on first call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


def _load_token() -> str | None:
    """Load the GoatCounter API token from disk, caching the result.

    Returns the token string on success, or None if the file does not exist
    yet.  Logs a warning on the first miss and subsequent misses at DEBUG
    level.
    """
    global _goatcounter_token
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
        logger.warning(
            "GoatCounter token not yet available at %s — analytics disabled until token appears",
            GOATCOUNTER_AUTH_FILE,
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
    analytics_enabled: bool | None,
    show_views_on_posts: bool | None,
) -> AnalyticsSettingsResponse:
    """Create or update analytics settings, applying only the provided fields.

    On first call, creates the singleton settings row. On subsequent calls,
    updates only the fields that are not None, leaving other fields unchanged.
    """
    result = await session.execute(select(AnalyticsSettings).limit(1))
    row = result.scalar_one_or_none()

    if row is None:
        row = AnalyticsSettings(
            analytics_enabled=True if analytics_enabled is None else analytics_enabled,
            show_views_on_posts=False if show_views_on_posts is None else show_views_on_posts,
        )
        session.add(row)
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
    """Fire-and-forget hit recording to GoatCounter.

    Skips recording when:
    - The request carries a valid authenticated user session.
    - The User-Agent is identified as a bot/crawler.
    - Analytics are disabled in settings.
    - The GoatCounter token is not yet available.

    Any failure is logged at WARNING level and never propagated to the caller.
    """
    try:
        # Skip authenticated users — admin/editor browsing should not inflate counts.
        if user is not None:
            return

        # Skip crawlers and bots.
        if _crawler_detect.is_crawler(user_agent):
            return

        # Skip if analytics disabled.
        settings = await get_analytics_settings(session)
        if not settings.analytics_enabled:
            return

        # Skip if token not available yet.
        token = _load_token()
        if token is None:
            return

        client = _get_http_client()
        await client.post(
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
    except Exception:
        logger.warning("Failed to record analytics hit for path %r", path, exc_info=True)


# ── Stats proxy ────────────────────────────────────────────────────────────────


async def _stats_request(
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> Any | None:
    """Authenticated GET to GoatCounter; returns parsed JSON or None on any error."""
    try:
        token = _load_token()
        if token is None:
            return None
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}{endpoint}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        logger.warning("GoatCounter stats request to %r failed", endpoint, exc_info=True)
        return None


async def fetch_total_stats(
    session: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> TotalStatsResponse:
    """Proxy GoatCounter total stats; returns zero counts when unavailable."""
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request("/api/v0/stats/total", params or None)
    if data is None:
        return TotalStatsResponse(total_views=0, total_unique=0)
    return TotalStatsResponse(
        total_views=data.get("total", 0),
        total_unique=data.get("total_unique", 0),
    )


async def fetch_path_hits(
    session: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> PathHitsResponse:
    """Proxy GoatCounter per-path hit counts; returns empty list when unavailable."""
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request("/api/v0/stats/hits", params or None)
    if data is None:
        return PathHitsResponse()
    paths = [
        PathHit(
            path=entry.get("path", ""),
            views=entry.get("count", 0),
            unique=entry.get("count_unique", 0),
        )
        for entry in data.get("hits", [])
    ]
    return PathHitsResponse(paths=paths)


async def fetch_path_referrers(
    session: AsyncSession,
    path_id: int,
) -> PathReferrersResponse:
    """Proxy GoatCounter referrer breakdown for a path; returns empty list when unavailable."""
    data = await _stats_request(f"/api/v0/stats/hits/{path_id}/referrers")
    if data is None:
        return PathReferrersResponse(path_id=path_id)
    referrers = [
        ReferrerEntry(
            referrer=entry.get("name", ""),
            count=entry.get("count", 0),
        )
        for entry in data.get("referrers", [])
    ]
    return PathReferrersResponse(path_id=path_id, referrers=referrers)


async def fetch_breakdown(
    session: AsyncSession,
    category: str,
    start: str | None = None,
    end: str | None = None,
) -> BreakdownResponse:
    """Proxy GoatCounter category breakdown (browser, OS, country, etc.).

    Returns empty entries list when GoatCounter is unavailable.
    """
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    data = await _stats_request(f"/api/v0/stats/{category}", params or None)
    if data is None:
        return BreakdownResponse(category=category)
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
