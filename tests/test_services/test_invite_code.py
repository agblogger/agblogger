"""Tests for invite code validation edge cases."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.models.user import User
from backend.services.auth_service import (
    create_invite_code,
    get_valid_invite_code,
    hash_password,
)
from backend.services.datetime_service import format_iso, now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


class TestInviteCodeValidation:
    async def test_expired_invite_is_rejected(self, session):
        """An expired invite code should return None."""
        now = format_iso(now_utc())
        user = User(
            username="invadmin",
            email="inv@test.com",
            password_hash=hash_password("pass"),
            display_name="Admin",
            is_admin=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        invite, code = await create_invite_code(session, user.id, expires_days=1)
        # Manually expire it
        invite.expires_at = format_iso(now_utc() - timedelta(days=1))
        await session.commit()

        result = await get_valid_invite_code(session, code)
        assert result is None

    async def test_used_invite_is_rejected(self, session):
        """A used invite code should return None."""
        now = format_iso(now_utc())
        user = User(
            username="invadmin2",
            email="inv2@test.com",
            password_hash=hash_password("pass"),
            display_name="Admin",
            is_admin=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        invite, code = await create_invite_code(session, user.id, expires_days=7)
        # Mark as used
        invite.used_at = now
        invite.used_by_user_id = user.id
        await session.commit()

        result = await get_valid_invite_code(session, code)
        assert result is None

    async def test_valid_invite_is_accepted(self, session):
        """A valid, unused, non-expired invite should be accepted."""
        now = format_iso(now_utc())
        user = User(
            username="invadmin3",
            email="inv3@test.com",
            password_hash=hash_password("pass"),
            display_name="Admin",
            is_admin=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        invite, code = await create_invite_code(session, user.id, expires_days=7)
        result = await get_valid_invite_code(session, code)
        assert result is not None
        assert result.id == invite.id

    async def test_nonexistent_code_returns_none(self, session):
        """A completely wrong invite code should return None."""
        result = await get_valid_invite_code(session, "aginvite_nonexistent")
        assert result is None
