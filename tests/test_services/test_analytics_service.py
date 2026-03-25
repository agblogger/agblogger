"""Tests for the analytics service settings management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.services.analytics_service import get_analytics_settings, update_analytics_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


async def test_get_default_settings(session: AsyncSession) -> None:
    """get_analytics_settings returns defaults when no row exists."""
    result = await get_analytics_settings(session)
    assert result.analytics_enabled is True
    assert result.show_views_on_posts is False


async def test_update_settings_creates_row(session: AsyncSession) -> None:
    """update_analytics_settings creates a row on first call."""
    result = await update_analytics_settings(
        session, analytics_enabled=False, show_views_on_posts=True
    )
    assert result.analytics_enabled is False
    assert result.show_views_on_posts is True

    # Verify persisted
    fetched = await get_analytics_settings(session)
    assert fetched.analytics_enabled is False
    assert fetched.show_views_on_posts is True


async def test_update_settings_partial(session: AsyncSession) -> None:
    """update_analytics_settings applies partial updates, leaving unchanged fields intact."""
    # Create initial row
    await update_analytics_settings(session, analytics_enabled=True, show_views_on_posts=False)

    # Partial update: only change analytics_enabled
    result = await update_analytics_settings(
        session, analytics_enabled=False, show_views_on_posts=None
    )
    assert result.analytics_enabled is False
    assert result.show_views_on_posts is False  # unchanged

    # Partial update: only change show_views_on_posts
    result2 = await update_analytics_settings(
        session, analytics_enabled=None, show_views_on_posts=True
    )
    assert result2.analytics_enabled is False  # unchanged from previous
    assert result2.show_views_on_posts is True
