"""Test that PAT last_used_at is updated on authentication."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import Base
from backend.models.user import User
from backend.services.auth_service import (
    authenticate_personal_access_token,
    create_personal_access_token,
    hash_password,
)
from backend.services.datetime_service import format_iso, now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


class TestPATLastUsedAt:
    async def test_authenticate_updates_last_used_at(self, session):
        """PAT last_used_at should be set after successful authentication."""
        now = format_iso(now_utc())
        user = User(
            username="patuser",
            email="pat@test.com",
            password_hash=hash_password("password"),
            display_name="PAT User",
            is_admin=False,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        pat, token_value = await create_personal_access_token(
            session, user.id, "test-token", expires_days=30
        )
        assert pat.last_used_at is None

        authed_user = await authenticate_personal_access_token(session, token_value)
        assert authed_user is not None
        assert authed_user.id == user.id

        await session.refresh(pat)
        assert pat.last_used_at is not None


class TestPATAuthentication:
    async def test_expired_pat_is_auto_revoked(self, session):
        """An expired PAT should be auto-revoked and raise TokenExpiredError."""
        from datetime import timedelta

        from backend.exceptions import TokenExpiredError

        now = format_iso(now_utc())
        user = User(
            username="expuser",
            email="exp@test.com",
            password_hash=hash_password("pass"),
            display_name="Exp",
            is_admin=False,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        pat, token_value = await create_personal_access_token(
            session, user.id, "expiring", expires_days=1
        )
        # Manually set expires_at to the past
        pat.expires_at = format_iso(now_utc() - timedelta(days=1))
        await session.commit()

        with pytest.raises(TokenExpiredError):
            await authenticate_personal_access_token(session, token_value)

        # Verify it was auto-revoked
        await session.refresh(pat)
        assert pat.revoked_at is not None

    async def test_revoked_pat_returns_none(self, session):
        """A revoked PAT should return None."""
        from backend.services.auth_service import revoke_personal_access_token

        now = format_iso(now_utc())
        user = User(
            username="revuser",
            email="rev@test.com",
            password_hash=hash_password("pass"),
            display_name="Rev",
            is_admin=False,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        pat, token_value = await create_personal_access_token(
            session, user.id, "to-revoke", expires_days=30
        )
        await revoke_personal_access_token(session, user.id, pat.id)

        result = await authenticate_personal_access_token(session, token_value)
        assert result is None

    async def test_nonexistent_token_returns_none(self, session):
        """A completely wrong token should return None."""
        result = await authenticate_personal_access_token(session, "agpat_nonexistent_token")
        assert result is None
