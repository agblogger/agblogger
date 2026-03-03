"""Tests for the post owner service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import Base
from backend.models.user import User
from backend.services.auth_service import hash_password
from backend.services.datetime_service import format_iso, now_utc
from backend.services.post_owner_service import build_owner_lookup, resolve_owner_username

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


async def _create_user(
    session: AsyncSession,
    username: str,
    display_name: str | None = None,
) -> User:
    ts = format_iso(now_utc())
    user = User(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password("password"),
        display_name=display_name,
        is_admin=False,
        created_at=ts,
        updated_at=ts,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


class TestResolveOwnerUsername:
    """Tests for resolve_owner_username (pure sync function)."""

    def test_author_username_direct_match(self) -> None:
        result = resolve_owner_username(
            author_username="alice",
            author="Alice Display",
            usernames={"alice", "bob"},
            unique_display_names={"Alice Display": "alice"},
        )
        assert result == "alice"

    def test_author_matches_a_username(self) -> None:
        result = resolve_owner_username(
            author_username=None,
            author="bob",
            usernames={"alice", "bob"},
            unique_display_names={},
        )
        assert result == "bob"

    def test_author_matches_unique_display_name(self) -> None:
        result = resolve_owner_username(
            author_username=None,
            author="Bob Smith",
            usernames={"alice", "bob"},
            unique_display_names={"Bob Smith": "bob"},
        )
        assert result == "bob"

    def test_returns_none_when_nothing_matches(self) -> None:
        result = resolve_owner_username(
            author_username=None,
            author="Unknown Author",
            usernames={"alice", "bob"},
            unique_display_names={"Bob Smith": "bob"},
        )
        assert result is None

    def test_duplicate_display_name_returns_none(self) -> None:
        """When the display name is shared by multiple users, it is not in unique_display_names."""
        result = resolve_owner_username(
            author_username=None,
            author="Shared Name",
            usernames={"alice", "bob"},
            unique_display_names={},
        )
        assert result is None


class TestBuildOwnerLookup:
    """Tests for build_owner_lookup (async, needs DB)."""

    async def test_returns_correct_usernames_and_unique_display_names(
        self, session: AsyncSession
    ) -> None:
        await _create_user(session, "alice", display_name="Alice Unique")
        await _create_user(session, "bob", display_name="Shared Name")
        await _create_user(session, "carol", display_name="Shared Name")
        await _create_user(session, "dave", display_name=None)

        usernames, unique_display_names = await build_owner_lookup(session)

        assert usernames == {"alice", "bob", "carol", "dave"}
        assert "Alice Unique" in unique_display_names
        assert unique_display_names["Alice Unique"] == "alice"
        # "Shared Name" is duplicated, so it should NOT appear in unique_display_names
        assert "Shared Name" not in unique_display_names
        # None display_name should not appear
        assert None not in unique_display_names
