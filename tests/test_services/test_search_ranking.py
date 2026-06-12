"""Ranking behaviour for full-text post search.

Covers three ordering guarantees:

1. Title matches outrank body-only matches (FTS5 column weighting), so a query
   that appears in a post's title surfaces above a post that merely mentions it
   in the body.
2. Equally-ranked posts fall back to a deterministic recency tiebreaker
   (newest first) instead of arbitrary rowid order.
3. Posts tied on relevance and creation time fall back to unique file-path
   ordering.
"""

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
    """SQLite engine with cache metadata and the FTS virtual table."""
    db_path = tmp_path / "test_search_ranking.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(CacheBase.metadata.create_all)
        await conn.execute(FTS_CREATE_SQL)
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
    content: str,
    subtitle: str = "",
    created_at: datetime,
) -> None:
    """Insert a cache row plus its FTS index entry."""
    post = PostCache(
        file_path=file_path,
        title=title,
        subtitle=subtitle or None,
        author="admin",
        created_at=created_at,
        modified_at=created_at,
        is_draft=False,
        content_hash=file_path,
        rendered_excerpt=None,
        rendered_html=f"<p>{content}</p>",
    )
    session.add(post)
    await session.flush()
    await session.execute(
        FTS_INSERT_SQL,
        {"rowid": post.id, "title": title, "subtitle": subtitle, "content": content},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_title_match_outranks_body_only_match(session: AsyncSession) -> None:
    """A title hit must rank above a body-only hit for the same term.

    The body-only post is a short document, so under equal column weights BM25
    would rank it first. Title weighting must flip the order.
    """
    when = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Body-only match, inserted first (lower rowid) and a short document.
    await _add_post(
        session,
        file_path="posts/body/index.md",
        title="Unrelated heading",
        content="rankingtargetword",
        created_at=when,
    )
    # Title match, longer body so length normalisation favours the other post.
    await _add_post(
        session,
        file_path="posts/title/index.md",
        title="rankingtargetword",
        content="alpha beta gamma delta epsilon zeta eta theta iota kappa",
        created_at=when,
    )

    results = await search_posts(session, "rankingtargetword")

    assert [r.file_path for r in results] == [
        "posts/title/index.md",
        "posts/body/index.md",
    ]


@pytest.mark.asyncio
async def test_equal_rank_breaks_ties_by_newest_first(session: AsyncSession) -> None:
    """Posts with identical relevance are ordered newest-first."""
    older = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    newer = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    # Identical FTS content => identical BM25 score. Insert the older one first
    # so a rowid-order fallback would (wrongly) place it ahead of the newer one.
    await _add_post(
        session,
        file_path="posts/older/index.md",
        title="tiebreakword",
        content="shared body content",
        created_at=older,
    )
    await _add_post(
        session,
        file_path="posts/newer/index.md",
        title="tiebreakword",
        content="shared body content",
        created_at=newer,
    )

    results = await search_posts(session, "tiebreakword")

    assert [r.file_path for r in results] == [
        "posts/newer/index.md",
        "posts/older/index.md",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("include_drafts", [False, True])
async def test_equal_rank_and_creation_time_breaks_ties_by_file_path(
    session: AsyncSession,
    *,
    include_drafts: bool,
) -> None:
    """Posts tied on relevance and creation time are ordered by unique file path."""
    when = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Insert in reverse file-path order so incidental rowid ordering cannot
    # satisfy the deterministic final tiebreaker.
    await _add_post(
        session,
        file_path="posts/z-last/index.md",
        title="finaltiebreakword",
        content="shared body content",
        created_at=when,
    )
    await _add_post(
        session,
        file_path="posts/a-first/index.md",
        title="finaltiebreakword",
        content="shared body content",
        created_at=when,
    )

    results = await search_posts(session, "finaltiebreakword", include_drafts=include_drafts)

    assert [r.file_path for r in results] == [
        "posts/a-first/index.md",
        "posts/z-last/index.md",
    ]
