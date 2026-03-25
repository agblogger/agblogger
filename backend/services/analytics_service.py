"""Analytics service: settings management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings
from backend.schemas.analytics import AnalyticsSettingsResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
