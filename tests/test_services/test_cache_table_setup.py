"""Regression tests for cache table setup and FTS virtual-table creation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.base import CacheBase
from backend.models.post import FTS_CREATE_SQL, FTS_INSERT_SQL, PostCache
from backend.services.post_service import search_posts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    """Create a SQLite engine using the generic cache metadata setup path."""
    db_path = tmp_path / "test_cache_table_setup.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(CacheBase.metadata.create_all)
        await conn.execute(FTS_CREATE_SQL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Create a session for the test database."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


@pytest.mark.asyncio
async def test_generic_cache_metadata_setup_keeps_posts_fts_searchable(
    session: AsyncSession,
) -> None:
    """Generic cache metadata creation must not replace the FTS virtual table."""
    post = PostCache(
        file_path="posts/hello/index.md",
        title="Hello World",
        subtitle=None,
        author="admin",
        created_at=datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC),
        modified_at=datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC),
        is_draft=False,
        content_hash="abc123",
        rendered_excerpt=None,
        rendered_html="<p>Hello World</p>",
    )
    session.add(post)
    await session.flush()
    await session.execute(
        FTS_INSERT_SQL,
        {
            "rowid": post.id,
            "title": post.title,
            "subtitle": "",
            "content": "Hello world body",
        },
    )
    await session.commit()

    results = await search_posts(session, "hello")

    assert [result.file_path for result in results] == ["posts/hello/index.md"]
