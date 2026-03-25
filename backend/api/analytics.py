"""Analytics API endpoints — admin stats proxy and public view count."""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session, require_admin
from backend.models.post import PostCache
from backend.models.user import User
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    AnalyticsSettingsUpdate,
    BreakdownCategory,
    BreakdownResponse,
    PathHitsResponse,
    PathReferrersResponse,
    TotalStatsResponse,
    ViewCountResponse,
)
from backend.services.analytics_service import (
    fetch_breakdown,
    fetch_path_hits,
    fetch_path_referrers,
    fetch_total_stats,
    fetch_view_count,
    get_analytics_settings,
    update_analytics_settings,
)
from backend.utils.slug import file_path_to_slug, is_directory_post_path, resolve_slug_candidates

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin/analytics", tags=["analytics-admin"])
public_router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_SAFE_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9/_.-]{1,200}$")


async def _resolve_public_post_slug(session: AsyncSession, file_path: str) -> str | None:
    """Resolve *file_path* to a published post slug or return None.

    Accepts either a bare slug (``hello``) or the canonical directory-backed
    file path (``posts/hello/index.md``). Draft, deleted, and otherwise
    non-public posts intentionally resolve to ``None`` so the public views
    endpoint stays non-enumerating.
    """
    normalized_path = file_path.strip().strip("/")
    if normalized_path == "":
        return None

    candidates: tuple[str, ...]
    if is_directory_post_path(normalized_path):
        candidates = (normalized_path,)
    elif normalized_path.startswith("posts/"):
        candidates = ()
    else:
        candidates = resolve_slug_candidates(normalized_path)

    for candidate in candidates:
        result = await session.execute(
            select(PostCache.file_path)
            .where(
                PostCache.file_path == candidate,
                PostCache.is_draft.is_(False),
            )
            .limit(1)
        )
        resolved_file_path = result.scalar_one_or_none()
        if resolved_file_path is not None:
            return file_path_to_slug(resolved_file_path)

    return None


# ── Admin endpoints ────────────────────────────────────────────────────────────


@admin_router.get("/settings", response_model=AnalyticsSettingsResponse)
async def get_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Get current analytics settings."""
    return await get_analytics_settings(session)


@admin_router.put("/settings", response_model=AnalyticsSettingsResponse)
async def update_settings(
    body: AnalyticsSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Update analytics settings."""
    return await update_analytics_settings(
        session,
        analytics_enabled=body.analytics_enabled,
        show_views_on_posts=body.show_views_on_posts,
    )


@admin_router.get("/stats/total", response_model=TotalStatsResponse)
async def get_total_stats(
    _user: Annotated[User, Depends(require_admin)],
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> TotalStatsResponse:
    """Get total aggregated stats from GoatCounter."""
    result = await fetch_total_stats(start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/hits", response_model=PathHitsResponse)
async def get_path_hits(
    _user: Annotated[User, Depends(require_admin)],
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> PathHitsResponse:
    """Get per-path hit counts from GoatCounter."""
    result = await fetch_path_hits(start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/hits/{path_id}", response_model=PathReferrersResponse)
async def get_path_referrers(
    path_id: int,
    _user: Annotated[User, Depends(require_admin)],
) -> PathReferrersResponse:
    """Get referrer breakdown for a specific path ID."""
    result = await fetch_path_referrers(path_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/{category}", response_model=BreakdownResponse)
async def get_breakdown(
    category: BreakdownCategory,
    _user: Annotated[User, Depends(require_admin)],
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> BreakdownResponse:
    """Get category breakdown stats (browsers, systems, locations, etc.) from GoatCounter."""
    result = await fetch_breakdown(category, start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


# ── Public endpoints ───────────────────────────────────────────────────────────


@public_router.get("/views/{file_path:path}", response_model=ViewCountResponse)
async def get_view_count(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ViewCountResponse:
    """Get public view count for a post.

    Returns the same response for non-existent, deleted, or draft posts to
    avoid information disclosure about post existence.
    """
    normalized_path = file_path.strip().strip("/")
    if not _SAFE_PATH_PATTERN.match(normalized_path):
        return ViewCountResponse(views=None)

    post_slug = await _resolve_public_post_slug(session, normalized_path)
    if post_slug is None:
        return ViewCountResponse(views=None)

    views = await fetch_view_count(session, f"/post/{post_slug}")
    return ViewCountResponse(views=views)
