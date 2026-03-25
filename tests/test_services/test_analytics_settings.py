"""Tests for the AnalyticsSettings durable model."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.models.analytics import AnalyticsSettings
from backend.models.base import DurableBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


async def test_default_analytics_settings(session: AsyncSession) -> None:
    """A fresh DB has no analytics_settings row."""
    result = await session.execute(select(AnalyticsSettings))
    rows = result.scalars().all()
    assert rows == []


async def test_create_analytics_settings(session: AsyncSession) -> None:
    """Can create and persist an analytics settings row."""
    settings = AnalyticsSettings(analytics_enabled=True, show_views_on_posts=False)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)

    assert settings.id is not None
    assert settings.analytics_enabled is True
    assert settings.show_views_on_posts is False

    # Verify it's retrievable from DB
    stmt = select(AnalyticsSettings).where(AnalyticsSettings.id == settings.id)
    result = await session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.analytics_enabled is True
    assert fetched.show_views_on_posts is False


async def test_singleton_check_constraint_rejects_id_not_one(
    db_engine: AsyncEngine, _create_tables: None
) -> None:
    """The CHECK CONSTRAINT ck_analytics_settings_singleton must reject id != 1."""
    async with db_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO analytics_settings (id, analytics_enabled, show_views_on_posts)"
                    " VALUES (2, 1, 0)"
                )
            )


async def test_singleton_check_constraint_allows_id_one(
    db_engine: AsyncEngine, _create_tables: None
) -> None:
    """The CHECK CONSTRAINT must allow id = 1."""
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO analytics_settings (id, analytics_enabled, show_views_on_posts)"
                " VALUES (1, 1, 0)"
            )
        )
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT id FROM analytics_settings WHERE id = 1"))
        row = result.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_default_id_is_one(session: AsyncSession) -> None:
    """When no explicit id given, default id should be 1."""
    settings = AnalyticsSettings(analytics_enabled=True, show_views_on_posts=False)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    assert settings.id == 1
