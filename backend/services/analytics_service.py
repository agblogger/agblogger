"""Analytics service: settings management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_analytics_settings(session: AsyncSession) -> AnalyticsSettings:
    """Return current analytics settings, falling back to defaults if no row exists.

    Returns an AnalyticsSettings instance with defaults (analytics_enabled=True,
    show_views_on_posts=False) when no row has been persisted yet. The returned
    instance is not added to the session; callers that need a persistent row
    should use update_analytics_settings instead.
    """
    result = await session.execute(select(AnalyticsSettings).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        return AnalyticsSettings(analytics_enabled=True, show_views_on_posts=False)
    return row


async def update_analytics_settings(
    session: AsyncSession,
    *,
    analytics_enabled: bool | None,
    show_views_on_posts: bool | None,
) -> AnalyticsSettings:
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
    return row
