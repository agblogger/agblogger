"""Unit tests for the authentication service."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.base import DurableBase
from backend.models.user import AdminRefreshToken, AdminUser
from backend.services.auth_service import (
    ALGORITHM,
    authenticate_admin,
    create_access_token,
    create_refresh_token_value,
    create_tokens,
    decode_access_token,
    ensure_admin_user,
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
) -> AdminUser:
    now = format_iso(now_utc())
    user = AdminUser(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password(password),
        display_name=username,
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
            {"sub": "42", "username": "alice"},
            test_settings.secret_key,
        )
        payload = jwt.decode(
            token,
            derive_access_token_key(test_settings.secret_key),
            algorithms=[ALGORITHM],
        )
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"
        assert payload["type"] == "access"

    def test_create_access_token_is_not_signed_with_raw_secret(
        self, test_settings: Settings
    ) -> None:
        token = create_access_token(
            {"sub": "42", "username": "alice"},
            test_settings.secret_key,
        )
        with pytest.raises(jwt.InvalidTokenError):
            jwt.decode(token, test_settings.secret_key, algorithms=[ALGORITHM])

    def test_decode_access_token_valid(self, test_settings: Settings) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob"},
            test_settings.secret_key,
        )
        payload = decode_access_token(token, test_settings.secret_key)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["username"] == "bob"

    def test_decode_access_token_rejects_expired(self, test_settings: Settings) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob"},
            test_settings.secret_key,
            expires_minutes=-1,
        )
        assert decode_access_token(token, test_settings.secret_key) is None

    def test_decode_access_token_rejects_wrong_type(self, test_settings: Settings) -> None:
        payload = {"sub": "1", "username": "bob", "type": "refresh"}
        token = jwt.encode(payload, test_settings.secret_key, algorithm=ALGORITHM)
        assert decode_access_token(token, test_settings.secret_key) is None


class TestRefreshTokenValue:
    def test_create_refresh_token_value_is_unique(self) -> None:
        a = create_refresh_token_value()
        b = create_refresh_token_value()
        assert a != b


class TestAuthenticateUser:
    async def test_authenticate_admin_valid(self, session: AsyncSession) -> None:
        await _create_user(session, username="valid", password="pass123")
        user = await authenticate_admin(session, "valid", "pass123")
        assert user is not None
        assert user.username == "valid"

    async def test_authenticate_admin_wrong_password(self, session: AsyncSession) -> None:
        await _create_user(session, username="locked", password="realpass")
        assert await authenticate_admin(session, "locked", "wrongpass") is None

    async def test_authenticate_admin_missing_user_still_checks_password(
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

        assert await authenticate_admin(session, "missing-user", "guess123") is None
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
            select(AdminRefreshToken).where(AdminRefreshToken.token_hash == token_hash)
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
            select(AdminRefreshToken).where(AdminRefreshToken.token_hash == old_hash)
        )
        assert result.scalar_one_or_none() is None

        new_hash = hash_token(new_refresh)
        result = await session.execute(
            select(AdminRefreshToken).where(AdminRefreshToken.token_hash == new_hash)
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
            select(AdminRefreshToken).where(AdminRefreshToken.token_hash == old_hash)
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


class TestEnsureAdminUser:
    """Tests for admin user bootstrap with display name configuration."""

    @pytest.mark.asyncio
    async def test_uses_explicit_display_name(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """When admin_display_name is set, use it instead of username."""
        test_settings.admin_display_name = "Jane Doe"
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        assert admin.display_name == "Jane Doe"

    @pytest.mark.asyncio
    async def test_falls_back_to_username_when_display_name_empty(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """When admin_display_name is empty, fall back to admin_username."""
        test_settings.admin_display_name = ""
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        assert admin.display_name == test_settings.admin_username

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_display_name(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """Whitespace-only display names should fall back to username."""
        test_settings.admin_display_name = "   "
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        assert admin.display_name == test_settings.admin_username

    @pytest.mark.asyncio
    async def test_updates_password_when_env_changes(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """Changing ADMIN_PASSWORD should update the stored hash on next startup."""
        test_settings.admin_password = "original_password"
        await ensure_admin_user(session, test_settings)

        # Change the env password and re-run bootstrap
        test_settings.admin_password = "new_password_123"
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        assert verify_password("new_password_123", admin.password_hash)
        assert not verify_password("original_password", admin.password_hash)

    @pytest.mark.asyncio
    async def test_preserves_password_when_env_unchanged(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """Re-running bootstrap with same password should not rehash."""
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        original_hash = admin.password_hash

        await ensure_admin_user(session, test_settings)
        await session.refresh(admin)
        assert admin.password_hash == original_hash

    @pytest.mark.asyncio
    async def test_updates_display_name_when_env_changes(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """Changing ADMIN_DISPLAY_NAME should update on next startup."""
        test_settings.admin_display_name = "Old Name"
        await ensure_admin_user(session, test_settings)

        test_settings.admin_display_name = "New Name"
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        assert admin.display_name == "New Name"

    @pytest.mark.asyncio
    async def test_corrupted_password_hash_does_not_crash(
        self,
        session: AsyncSession,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A corrupted password_hash on an existing admin should not crash ensure_admin_user.

        When verify_password or hash_password raises an unexpected exception, the error must
        be logged and the sync skipped — the server must never crash on startup.
        """
        await ensure_admin_user(session, test_settings)

        # Simulate verify_password raising (e.g. due to an unforeseen bcrypt error).
        def _raise_on_verify(plain: str, hashed: str) -> bool:
            raise RuntimeError("bcrypt internal error — simulated corruption")

        monkeypatch.setattr("backend.services.auth_service.verify_password", _raise_on_verify)

        # Re-running bootstrap must not raise.
        with caplog.at_level(logging.ERROR, logger="backend.services.auth_service"):
            await ensure_admin_user(session, test_settings)

        assert any("password" in record.message.lower() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_updated_at_advances_after_password_sync(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """updated_at should be later than created_at after a password change sync."""
        test_settings.admin_password = "first_password"
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        created_at = admin.created_at

        test_settings.admin_password = "second_password"
        await ensure_admin_user(session, test_settings)
        await session.refresh(admin)

        assert admin.updated_at > created_at

    @pytest.mark.asyncio
    async def test_updated_at_unchanged_on_noop(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """updated_at must not change when ensure_admin_user runs with nothing to sync."""
        await ensure_admin_user(session, test_settings)

        stmt = select(AdminUser).where(AdminUser.username == test_settings.admin_username)
        result = await session.execute(stmt)
        admin = result.scalar_one()
        original_updated_at = admin.updated_at

        # Second call with identical settings — nothing should change.
        await ensure_admin_user(session, test_settings)
        await session.refresh(admin)

        assert admin.updated_at == original_updated_at
