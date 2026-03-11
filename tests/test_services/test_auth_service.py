"""Unit tests for the authentication service."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.base import DurableBase
from backend.models.user import InviteCode, RefreshToken, User
from backend.services.auth_service import (
    ALGORITHM,
    authenticate_user,
    consume_invite_code,
    create_access_token,
    create_refresh_token_value,
    create_tokens,
    decode_access_token,
    hash_password,
    hash_token,
    refresh_tokens,
    verify_password,
)
from backend.services.datetime_service import format_iso, now_utc
from backend.services.key_derivation import derive_access_token_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from backend.config import Settings


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


_DEFAULT_PASSWORD = "correcthorse"


async def _create_user(
    session: AsyncSession,
    username: str = "testuser",
    password: str = _DEFAULT_PASSWORD,
    is_admin: bool = False,
) -> User:
    now = format_iso(now_utc())
    user = User(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password(password),
        display_name=username,
        is_admin=is_admin,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_hash(self) -> None:
        hashed = hash_password("mypassword")
        assert hashed.startswith("$2b$")

    def test_verify_password_correct(self) -> None:
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_verify_password_incorrect(self) -> None:
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False


class TestVerifyPasswordSafety:
    """verify_password returns False on malformed hashes instead of crashing."""

    def test_empty_hash_returns_false(self) -> None:
        assert verify_password("password", "") is False

    def test_malformed_hash_returns_false(self) -> None:
        assert verify_password("password", "not-a-bcrypt-hash") is False

    def test_none_like_hash_returns_false(self) -> None:
        assert verify_password("password", "None") is False


class TestAccessTokens:
    def test_create_access_token_contains_claims(self, test_settings: Settings) -> None:
        token = create_access_token(
            {"sub": "42", "username": "alice", "is_admin": True},
            test_settings.secret_key,
        )
        payload = jwt.decode(
            token,
            derive_access_token_key(test_settings.secret_key),
            algorithms=[ALGORITHM],
        )
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"
        assert payload["is_admin"] is True
        assert payload["type"] == "access"

    def test_create_access_token_is_not_signed_with_raw_secret(
        self, test_settings: Settings
    ) -> None:
        token = create_access_token(
            {"sub": "42", "username": "alice", "is_admin": True},
            test_settings.secret_key,
        )
        with pytest.raises(jwt.InvalidTokenError):
            jwt.decode(token, test_settings.secret_key, algorithms=[ALGORITHM])

    def test_decode_access_token_valid(self, test_settings: Settings) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob", "is_admin": False},
            test_settings.secret_key,
        )
        payload = decode_access_token(token, test_settings.secret_key)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["username"] == "bob"

    def test_decode_access_token_rejects_expired(self, test_settings: Settings) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob", "is_admin": False},
            test_settings.secret_key,
            expires_minutes=-1,
        )
        assert decode_access_token(token, test_settings.secret_key) is None

    def test_decode_access_token_rejects_wrong_type(self, test_settings: Settings) -> None:
        payload = {"sub": "1", "username": "bob", "is_admin": False, "type": "refresh"}
        token = jwt.encode(payload, test_settings.secret_key, algorithm=ALGORITHM)
        assert decode_access_token(token, test_settings.secret_key) is None


class TestRefreshTokenValue:
    def test_create_refresh_token_value_is_unique(self) -> None:
        a = create_refresh_token_value()
        b = create_refresh_token_value()
        assert a != b


class TestAuthenticateUser:
    async def test_authenticate_user_valid(self, session: AsyncSession) -> None:
        await _create_user(session, username="valid", password="pass123")
        user = await authenticate_user(session, "valid", "pass123")
        assert user is not None
        assert user.username == "valid"

    async def test_authenticate_user_wrong_password(self, session: AsyncSession) -> None:
        await _create_user(session, username="locked", password="realpass")
        assert await authenticate_user(session, "locked", "wrongpass") is None

    async def test_authenticate_user_missing_user_still_checks_password(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []

        def fake_verify_password(plain_password: str, hashed_password: str) -> bool:
            calls.append((plain_password, hashed_password))
            return False

        monkeypatch.setattr(
            "backend.services.auth_service.verify_password",
            fake_verify_password,
        )

        assert await authenticate_user(session, "missing-user", "guess123") is None
        assert len(calls) == 1
        assert calls[0][0] == "guess123"


class TestTokenLifecycle:
    async def test_create_tokens_stores_refresh_in_db(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        user = await _create_user(session)
        access, refresh = await create_tokens(session, user, test_settings)

        assert access
        assert refresh

        token_hash = hash_token(refresh)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        stored = result.scalar_one_or_none()
        assert stored is not None
        assert stored.user_id == user.id

    async def test_refresh_tokens_rotates_token(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        user = await _create_user(session)
        _, original_refresh = await create_tokens(session, user, test_settings)

        new_pair = await refresh_tokens(session, original_refresh, test_settings)
        assert new_pair is not None
        new_access, new_refresh = new_pair

        assert new_access
        assert new_refresh
        assert new_refresh != original_refresh

        old_hash = hash_token(original_refresh)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == old_hash)
        )
        assert result.scalar_one_or_none() is None

        new_hash = hash_token(new_refresh)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == new_hash)
        )
        assert result.scalar_one_or_none() is not None

    async def test_refresh_token_single_use_under_concurrency(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        user = await _create_user(session, username="race-user")
        _, original_refresh = await create_tokens(session, user, test_settings)

        bind = session.bind
        assert bind is not None
        session_factory = async_sessionmaker(
            bind=bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async def _try_refresh() -> tuple[str, str] | None:
            async with session_factory() as worker_session:
                return await refresh_tokens(worker_session, original_refresh, test_settings)

        first, second = await asyncio.gather(_try_refresh(), _try_refresh())
        successes = [result for result in (first, second) if result is not None]
        assert len(successes) == 1

        # Old token must be gone regardless of concurrency ordering.
        old_hash = hash_token(original_refresh)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == old_hash)
        )
        assert result.scalar_one_or_none() is None

    async def test_refresh_token_race_logs_warning(
        self,
        session: AsyncSession,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When a refresh token is already consumed by a concurrent request, a warning is logged."""
        user = await _create_user(session, username="race-log-user")
        _, refresh_value = await create_tokens(session, user, test_settings)

        bind = session.bind
        assert bind is not None
        session_factory = async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)

        async def _try_refresh() -> tuple[str, str] | None:
            async with session_factory() as worker_session:
                return await refresh_tokens(worker_session, refresh_value, test_settings)

        with caplog.at_level(logging.WARNING, logger="backend.services.auth_service"):
            first, second = await asyncio.gather(_try_refresh(), _try_refresh())

        successes = [r for r in (first, second) if r is not None]
        assert len(successes) == 1
        assert any("already consumed" in record.message for record in caplog.records)


class TestInviteConsumption:
    async def test_consume_invite_code_single_use_under_concurrency(
        self, session: AsyncSession
    ) -> None:
        creator = await _create_user(session, username="invite-creator")
        user_a = await _create_user(session, username="invite-a")
        user_b = await _create_user(session, username="invite-b")

        now = format_iso(now_utc())
        invite = InviteCode(
            code_hash=hash_token("aginvite_test_token"),
            created_by_user_id=creator.id,
            created_at=now,
            expires_at=format_iso(now_utc()),
        )
        session.add(invite)
        await session.commit()
        await session.refresh(invite)

        bind = session.bind
        assert bind is not None
        session_factory = async_sessionmaker(
            bind=bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async def _consume(user_id: int) -> bool:
            async with session_factory() as worker_session:
                consumed = await consume_invite_code(
                    worker_session, invite_id=invite.id, used_by_user_id=user_id, used_at=now
                )
                await worker_session.commit()
                return consumed

        first, second = await asyncio.gather(_consume(user_a.id), _consume(user_b.id))
        assert {first, second} == {True, False}

    async def test_consume_invite_code_race_logs_warning(
        self, session: AsyncSession, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When an invite code is already consumed, a warning is logged."""
        creator = await _create_user(session, username="invite-log-creator")
        user = await _create_user(session, username="invite-log-user")

        now = format_iso(now_utc())
        future = format_iso(now_utc() + timedelta(days=7))
        invite = InviteCode(
            code_hash=hash_token("aginvite_race_log_test"),
            created_by_user_id=creator.id,
            created_at=now,
            expires_at=future,
        )
        session.add(invite)
        await session.commit()
        await session.refresh(invite)

        # Consume once — should succeed.
        consumed = await consume_invite_code(
            session, invite_id=invite.id, used_by_user_id=user.id, used_at=now
        )
        await session.commit()
        assert consumed is True

        # Attempt to consume again — should fail and log a warning.
        with caplog.at_level(logging.WARNING, logger="backend.services.auth_service"):
            consumed_again = await consume_invite_code(
                session, invite_id=invite.id, used_by_user_id=user.id, used_at=now
            )

        assert consumed_again is False
        assert any("already consumed" in record.message for record in caplog.records)
