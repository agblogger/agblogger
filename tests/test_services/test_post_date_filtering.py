"""Tests for date range filtering in list_posts.

Regression: a bare date to_date like "2026-01-15" must include posts from
the ENTIRE day (up to 23:59:59.999999), not just midnight (00:00:00).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.base import CacheBase, DurableBase
from backend.models.post import PostCache
from backend.services.post_service import list_posts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    db_path = tmp_path / "test_date_filter.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)
        await conn.run_sync(CacheBase.metadata.create_all)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                "title, content, content='posts_cache', content_rowid='id')"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


async def _add_post(
    session: AsyncSession,
    *,
    file_path: str,
    title: str,
    created_at: datetime,
) -> PostCache:
    post = PostCache(
        file_path=file_path,
        title=title,
        author="admin",
        created_at=created_at,
        modified_at=created_at,
        is_draft=False,
        content_hash="abc",
        rendered_excerpt=None,
        rendered_html="<p>test</p>",
    )
    session.add(post)
    await session.flush()
    return post


class TestToDateInclusivity:
    """to_date with a bare date must include posts from the entire day."""

    @pytest.mark.asyncio
    async def test_bare_date_to_date_includes_afternoon_post(self, session: AsyncSession) -> None:
        """A post created at 14:00 on 2026-01-15 must appear when to_date='2026-01-15'."""
        await _add_post(
            session,
            file_path="posts/morning/index.md",
            title="Morning",
            created_at=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
        )
        await _add_post(
            session,
            file_path="posts/afternoon/index.md",
            title="Afternoon",
            created_at=datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC),
        )
        await _add_post(
            session,
            file_path="posts/next-day/index.md",
            title="Next Day",
            created_at=datetime(2026, 1, 16, 10, 0, 0, tzinfo=UTC),
        )
        await session.commit()

        result = await list_posts(session, to_date="2026-01-15")
        titles = [p.title for p in result.posts]
        assert "Morning" in titles
        assert "Afternoon" in titles
        assert "Next Day" not in titles

    @pytest.mark.asyncio
    async def test_bare_date_to_date_includes_end_of_day_post(self, session: AsyncSession) -> None:
        """A post created at 23:59 on 2026-01-15 must appear when to_date='2026-01-15'."""
        await _add_post(
            session,
            file_path="posts/late-night/index.md",
            title="Late Night",
            created_at=datetime(2026, 1, 15, 23, 59, 59, tzinfo=UTC),
        )
        await session.commit()

        result = await list_posts(session, to_date="2026-01-15")
        assert len(result.posts) == 1
        assert result.posts[0].title == "Late Night"

    @pytest.mark.asyncio
    async def test_iso_datetime_to_date_preserves_exact_time(self, session: AsyncSession) -> None:
        """A full ISO datetime to_date should use the exact time, not end-of-day."""
        await _add_post(
            session,
            file_path="posts/before/index.md",
            title="Before",
            created_at=datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC),
        )
        await _add_post(
            session,
            file_path="posts/after/index.md",
            title="After",
            created_at=datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC),
        )
        await session.commit()

        result = await list_posts(session, to_date="2026-01-15T12:00:00+00:00")
        titles = [p.title for p in result.posts]
        assert "Before" in titles
        assert "After" not in titles
