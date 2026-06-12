"""Tests that list_posts surfaces word_count on each PostSummary.

Reading time is shown on the timeline, where it is derived from word_count.
The post list response must therefore include word_count for every summary,
not only the single-post detail response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.base import CacheBase, DurableBase
from backend.models.post import FTS_CREATE_SQL, PostCache
from backend.services.post_service import list_posts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    db_path = tmp_path / "test_word_count.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)
        await conn.run_sync(CacheBase.metadata.create_all)
    async with eng.begin() as conn:
        await conn.execute(FTS_CREATE_SQL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


async def _add_post(session: AsyncSession, *, file_path: str, word_count: int) -> None:
    now = datetime.now(UTC)
    post = PostCache(
        file_path=file_path,
        title="Post",
        author="admin",
        created_at=now,
        modified_at=now,
        is_draft=False,
        content_hash="abc",
        rendered_excerpt=None,
        rendered_html="<p>test</p>",
        word_count=word_count,
    )
    session.add(post)
    await session.flush()


@pytest.mark.asyncio
async def test_list_posts_includes_word_count(session: AsyncSession) -> None:
    """Each PostSummary in the list response carries its post's word_count."""
    await _add_post(session, file_path="posts/long/index.md", word_count=1234)
    await session.commit()

    result = await list_posts(session)

    assert len(result.posts) == 1
    assert result.posts[0].word_count == 1234
