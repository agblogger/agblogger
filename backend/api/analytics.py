"""Analytics API endpoints — admin stats proxy and public view count."""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session, require_admin
from backend.models.post import PostCache
from backend.models.user import AdminUser
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    AnalyticsSettingsUpdate,
    BreakdownDetailCategory,
    BreakdownDetailResponse,
    DashboardResponse,
    PathReferrersResponse,
    ViewCountResponse,
)
from backend.services.analytics_service import (
    fetch_breakdown_detail,
    fetch_dashboard,
    fetch_path_referrers,
    fetch_view_count,
    get_analytics_settings,
    update_analytics_settings,
)
from backend.utils.datetime import parse_datetime
from backend.utils.slug import file_path_to_slug, is_directory_post_path, resolve_slug_candidates

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin/analytics", tags=["analytics-admin"])
public_router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Restrict public file_path to safe characters and bounded length to prevent
# path traversal, injection, and abuse of the GoatCounter filter API.
_SAFE_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9/_.-]{1,200}$")
_ANALYTICS_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ANALYTICS_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:Z|[+-]\d{2}:\d{2}|[+-]\d{2})?$"
)


def _validate_analytics_range_param(value: str | None, name: str) -> str | None:
    """Accept a date or datetime string and reject unparseable range parameters."""
    if value is None:
        return None
    if not (
        _ANALYTICS_DATE_PATTERN.fullmatch(value) or _ANALYTICS_DATETIME_PATTERN.fullmatch(value)
    ):
        raise HTTPException(status_code=422, detail=f"Invalid {name} parameter")
    try:
        parse_datetime(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {name} parameter") from exc
    return value


async def _resolve_public_post_slug(session: AsyncSession, file_path: str) -> str | None:
    """Resolve *file_path* to a published post slug or return None.

    Accepts either a bare slug (``hello``) or the canonical directory-backed
    file path (``posts/hello/index.md``). Paths starting with ``posts/`` that
    do not match the canonical directory-backed form are rejected. Draft,
    deleted, and otherwise non-public posts intentionally resolve to ``None``
    so the public views endpoint stays non-enumerating.
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
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Get current analytics settings."""
    return await get_analytics_settings(session)


@admin_router.put("/settings", response_model=AnalyticsSettingsResponse)
async def update_settings(
    body: AnalyticsSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Update analytics settings."""
    return await update_analytics_settings(
        session,
        analytics_enabled=body.analytics_enabled,
        show_views_on_posts=body.show_views_on_posts,
    )


@admin_router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> DashboardResponse:
    """Get all dashboard analytics data in a single request.

    Fetches GoatCounter endpoints in parallel via asyncio.gather, combining
    the hits response for both path hits and views-over-time.
    """
    start = _validate_analytics_range_param(start, "start")
    end = _validate_analytics_range_param(end, "end")
    result = await fetch_dashboard(session, start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/hits/{path_id}", response_model=PathReferrersResponse)
async def get_path_referrers(
    path_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> PathReferrersResponse:
    """Get referrer breakdown for a specific path ID."""
    result = await fetch_path_referrers(session, path_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/{category}/{entry_id}", response_model=BreakdownDetailResponse)
async def get_breakdown_detail(
    category: BreakdownDetailCategory,
    entry_id: Annotated[str, Path(min_length=1, max_length=200)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> BreakdownDetailResponse:
    """Get version detail for a breakdown entry (browsers/systems only)."""
    result = await fetch_breakdown_detail(session, category, entry_id)
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
    if ".." in normalized_path:
        return ViewCountResponse(views=None)

    post_slug = await _resolve_public_post_slug(session, normalized_path)
    if post_slug is None:
        return ViewCountResponse(views=None)

    views = await fetch_view_count(session, f"/post/{post_slug}")
    return ViewCountResponse(views=views)
