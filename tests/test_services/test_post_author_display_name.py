"""Tests for author display name resolution in post queries.

Posts store a username in PostCache.author. The API response should resolve
this to the user's display_name via a LEFT JOIN, falling back to the raw
username when the user does not exist or has no display_name.
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
from backend.models.user import AdminUser
from backend.services.post_service import get_post, list_posts, resolve_author_display_name

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    """Create an in-memory SQLite engine with all tables."""
    db_path = tmp_path / "test_display_name.db"
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
    """Create a session for the test database."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


async def _create_user(
    session: AsyncSession,
    *,
    username: str,
    display_name: str | None = None,
) -> AdminUser:
    """Insert a user row and return it."""
    now = datetime.now(UTC).isoformat()
    user = AdminUser(
        username=username,
        email=f"{username}@test.com",
        password_hash="fakehash",
        display_name=display_name,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_post(
    session: AsyncSession,
    *,
    file_path: str,
    title: str,
    author: str | None = None,
    is_draft: bool = False,
) -> PostCache:
    """Insert a PostCache row and return it."""
    now = datetime.now(UTC)
    post = PostCache(
        file_path=file_path,
        title=title,
        author=author,
        created_at=now,
        modified_at=now,
        is_draft=is_draft,
        content_hash="abc123",
        rendered_excerpt=None,
        rendered_html="<p>test</p>",
    )
    session.add(post)
    await session.flush()
    return post


class TestListPostsAuthorDisplayName:
    """list_posts should resolve author display names via JOIN."""

    @pytest.mark.asyncio
    async def test_resolves_display_name(self, session: AsyncSession) -> None:
        """Post by 'admin' where admin has display_name='John Smith' returns 'John Smith'."""
        await _create_user(session, username="admin", display_name="John Smith")
        await _create_post(session, file_path="posts/hello/index.md", title="Hello", author="admin")
        await session.commit()

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author == "John Smith"

    @pytest.mark.asyncio
    async def test_fallback_for_deleted_user(self, session: AsyncSession) -> None:
        """Post by 'deleteduser' where no user exists returns 'deleteduser'."""
        await _create_post(
            session, file_path="posts/orphan/index.md", title="Orphan", author="deleteduser"
        )
        await session.commit()

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author == "deleteduser"

    @pytest.mark.asyncio
    async def test_fallback_for_null_display_name(self, session: AsyncSession) -> None:
        """Post by 'nodisplay' where user has display_name=None returns 'nodisplay'."""
        await _create_user(session, username="nodisplay", display_name=None)
        await _create_post(
            session,
            file_path="posts/plain/index.md",
            title="Plain",
            author="nodisplay",
        )
        await session.commit()

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author == "nodisplay"

    @pytest.mark.asyncio
    async def test_filter_by_display_name(self, session: AsyncSession) -> None:
        """Filtering by author=John should match the display name, not the username."""
        await _create_user(session, username="admin", display_name="John Smith")
        await _create_post(session, file_path="posts/a/index.md", title="Post A", author="admin")
        await session.commit()

        # Should match "John" in display name
        result = await list_posts(session, author="John")
        assert len(result.posts) == 1
        assert result.posts[0].title == "Post A"

        # Should NOT match "admin" (the raw username) when display name is set
        # Actually, COALESCE means we search the resolved name. "admin" != "John Smith"
        result_raw = await list_posts(session, author="admin")
        assert len(result_raw.posts) == 0

    @pytest.mark.asyncio
    async def test_filter_by_username_fallback(self, session: AsyncSession) -> None:
        """When user has no display name, filtering by username still works."""
        await _create_user(session, username="nodisplay", display_name=None)
        await _create_post(
            session,
            file_path="posts/b/index.md",
            title="Post B",
            author="nodisplay",
        )
        await session.commit()

        result = await list_posts(session, author="nodisplay")
        assert len(result.posts) == 1
        assert result.posts[0].title == "Post B"

    @pytest.mark.asyncio
    async def test_sort_by_author_uses_display_name(self, session: AsyncSession) -> None:
        """Sorting by author should sort on the resolved display name."""
        await _create_user(session, username="alice", display_name="Zara")
        await _create_user(session, username="bob", display_name="Albert")
        await _create_post(session, file_path="posts/p1/index.md", title="Post 1", author="alice")
        await _create_post(session, file_path="posts/p2/index.md", title="Post 2", author="bob")
        await session.commit()

        # Sort ascending by author. Albert < Zara, so Post 2 first.
        result = await list_posts(session, sort="author", order="asc")
        assert len(result.posts) == 2
        assert result.posts[0].author == "Albert"
        assert result.posts[1].author == "Zara"


class TestGetPostAuthorDisplayName:
    """get_post should resolve author display names via JOIN."""

    @pytest.mark.asyncio
    async def test_resolves_display_name(self, session: AsyncSession) -> None:
        """get_post returns display_name for an existing user."""
        await _create_user(session, username="admin", display_name="John Smith")
        await _create_post(session, file_path="posts/hello/index.md", title="Hello", author="admin")
        await session.commit()

        result = await get_post(session, "posts/hello/index.md")
        assert result is not None
        assert result.author == "John Smith"

    @pytest.mark.asyncio
    async def test_fallback_for_deleted_user(self, session: AsyncSession) -> None:
        """get_post returns raw username when user doesn't exist."""
        await _create_post(
            session, file_path="posts/orphan/index.md", title="Orphan", author="deleteduser"
        )
        await session.commit()

        result = await get_post(session, "posts/orphan/index.md")
        assert result is not None
        assert result.author == "deleteduser"

    @pytest.mark.asyncio
    async def test_fallback_for_null_display_name(self, session: AsyncSession) -> None:
        """get_post returns username when user's display_name is None."""
        await _create_user(session, username="nodisplay", display_name=None)
        await _create_post(
            session,
            file_path="posts/plain/index.md",
            title="Plain",
            author="nodisplay",
        )
        await session.commit()

        result = await get_post(session, "posts/plain/index.md")
        assert result is not None
        assert result.author == "nodisplay"

    @pytest.mark.asyncio
    async def test_draft_hidden_without_owner(self, session: AsyncSession) -> None:
        """get_post hides drafts when no draft_owner_username is given."""
        await _create_post(
            session, file_path="posts/draft/index.md", title="Draft", author="admin", is_draft=True
        )
        await session.commit()

        assert await get_post(session, "posts/draft/index.md") is None

    @pytest.mark.asyncio
    async def test_draft_visible_to_owner(self, session: AsyncSession) -> None:
        """get_post returns draft when draft_owner_username matches author."""
        await _create_user(session, username="admin", display_name="Admin")
        await _create_post(
            session, file_path="posts/draft/index.md", title="Draft", author="admin", is_draft=True
        )
        await session.commit()

        result = await get_post(session, "posts/draft/index.md", draft_owner_username="admin")
        assert result is not None
        assert result.title == "Draft"
        assert result.author == "Admin"

    @pytest.mark.asyncio
    async def test_draft_hidden_from_wrong_user(self, session: AsyncSession) -> None:
        """get_post hides drafts from users who are not the author."""
        await _create_post(
            session, file_path="posts/draft/index.md", title="Draft", author="alice", is_draft=True
        )
        await session.commit()

        assert await get_post(session, "posts/draft/index.md", draft_owner_username="bob") is None


class TestResolveAuthorDisplayName:
    """Unit tests for the resolve_author_display_name function."""

    @pytest.mark.asyncio
    async def test_returns_display_name(self, session: AsyncSession) -> None:
        """Returns display_name when user exists and has one."""
        await _create_user(session, username="admin", display_name="John Smith")
        await session.commit()

        assert await resolve_author_display_name(session, "admin") == "John Smith"

    @pytest.mark.asyncio
    async def test_returns_username_when_no_display_name(self, session: AsyncSession) -> None:
        """Returns username when user exists but display_name is None."""
        await _create_user(session, username="nodisplay", display_name=None)
        await session.commit()

        assert await resolve_author_display_name(session, "nodisplay") == "nodisplay"

    @pytest.mark.asyncio
    async def test_returns_username_when_user_missing(self, session: AsyncSession) -> None:
        """Returns raw username when no matching user exists."""
        assert await resolve_author_display_name(session, "ghost") == "ghost"

    @pytest.mark.asyncio
    async def test_returns_none_for_none(self, session: AsyncSession) -> None:
        """Returns None when username is None."""
        assert await resolve_author_display_name(session, None) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_string(self, session: AsyncSession) -> None:
        """Returns empty string when username is empty (falsy guard)."""
        assert await resolve_author_display_name(session, "") == ""

    @pytest.mark.asyncio
    async def test_returns_username_for_empty_display_name(self, session: AsyncSession) -> None:
        """Returns username when user has empty-string display_name."""
        await _create_user(session, username="emptydn", display_name="")
        await session.commit()

        assert await resolve_author_display_name(session, "emptydn") == "emptydn"


class TestNullAuthorInQueries:
    """Posts with author=None should not crash queries."""

    @pytest.mark.asyncio
    async def test_list_posts_with_null_author(self, session: AsyncSession) -> None:
        """list_posts handles PostCache.author=None gracefully."""
        await _create_post(session, file_path="posts/no-author/index.md", title="No Author")
        await session.commit()

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author is None

    @pytest.mark.asyncio
    async def test_get_post_with_null_author(self, session: AsyncSession) -> None:
        """get_post handles PostCache.author=None gracefully."""
        await _create_post(session, file_path="posts/no-author/index.md", title="No Author")
        await session.commit()

        result = await get_post(session, "posts/no-author/index.md")
        assert result is not None
        assert result.author is None
