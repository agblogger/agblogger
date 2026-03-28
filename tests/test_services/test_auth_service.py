"""Unit tests for the authentication service."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.exceptions import InternalServerError
from backend.filesystem.content_manager import ContentManager
from backend.models.base import DurableBase
from backend.models.crosspost import CrossPost, SocialAccount
from backend.models.user import AdminRefreshToken, AdminUser
from backend.schemas.crosspost import CrossPostStatus
from backend.services.auth_service import (
    ALGORITHM,
    _collapse_admin_identities,
    authenticate_admin,
    create_access_token,
    create_refresh_token_value,
    create_tokens,
    decode_access_token,
    ensure_admin_user,
    hash_password,
    hash_token,
    refresh_tokens,
    update_author_in_posts,
    verify_password,
)
from backend.services.key_derivation import derive_access_token_key
from backend.utils.datetime import format_iso, now_utc

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

    from backend.config import Settings
    from backend.filesystem.frontmatter import PostData


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


class TestAccessTokenClaimsExclusion:
    """Ensure sensitive fields are NOT included in JWT claims."""

    def test_is_admin_not_in_access_token_payload(self, test_settings: Settings) -> None:
        """is_admin must NOT be present in the access token payload.

        Prevents accidental re-introduction of role claims during future merges.
        """
        token = create_access_token(
            {"sub": "1", "username": "admin"},
            test_settings.secret_key,
        )
        payload = decode_access_token(token, test_settings.secret_key)
        assert payload is not None
        assert "is_admin" not in payload


class TestDecodeAccessTokenLogLevels:
    """decode_access_token must log expired tokens at DEBUG and invalid tokens at WARNING."""

    def test_expired_token_logged_at_debug(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob"},
            test_settings.secret_key,
            expires_minutes=-1,
        )
        with caplog.at_level(logging.DEBUG, logger="backend.services.auth_service"):
            result = decode_access_token(token, test_settings.secret_key)

        assert result is None
        debug_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "expired" in r.message.lower()
        ]
        assert len(debug_records) >= 1

    def test_invalid_signature_logged_at_warning(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        token = create_access_token(
            {"sub": "1", "username": "bob"},
            test_settings.secret_key,
        )
        with caplog.at_level(logging.DEBUG, logger="backend.services.auth_service"):
            result = decode_access_token(token, "wrong-secret-key-that-is-long-enough")

        assert result is None
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "invalid" in r.message.lower()
        ]
        assert len(warning_records) >= 1

    def test_malformed_token_logged_at_warning(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="backend.services.auth_service"):
            result = decode_access_token("not-a-jwt-token", test_settings.secret_key)

        assert result is None
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "invalid" in r.message.lower()
        ]
        assert len(warning_records) >= 1


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

        When verify_password raises ValueError (e.g. bad hash format), the error must
        be logged and the sync skipped — the server must never crash on startup.
        """
        await ensure_admin_user(session, test_settings)

        # Simulate verify_password raising ValueError (bad hash format — bcrypt known failure mode).
        def _raise_on_verify(plain: str, hashed: str) -> bool:
            raise ValueError("bcrypt bad hash format — simulated corruption")

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

    @pytest.mark.asyncio
    async def test_renames_existing_single_admin_to_configured_username(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """A username change must not leave the old admin identity live."""
        legacy_admin = await _create_user(
            session,
            username="legacy-admin",
            password="legacy-password",
        )
        _, legacy_refresh = await create_tokens(session, legacy_admin, test_settings)

        test_settings.admin_username = "configured-admin"
        test_settings.admin_password = "configured-password"

        await ensure_admin_user(session, test_settings)

        result = await session.execute(select(AdminUser).order_by(AdminUser.id))
        admins = list(result.scalars().all())
        assert len(admins) == 1

        admin = admins[0]
        assert admin.id == legacy_admin.id
        assert admin.username == "configured-admin"
        assert await authenticate_admin(session, "legacy-admin", "legacy-password") is None

        authed = await authenticate_admin(session, "configured-admin", "configured-password")
        assert authed is not None
        assert authed.id == legacy_admin.id

        refresh_result = await session.execute(
            select(AdminRefreshToken).where(
                AdminRefreshToken.token_hash == hash_token(legacy_refresh)
            )
        )
        assert refresh_result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_rewrites_existing_post_authors_when_startup_username_changes(
        self,
        session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir,
        test_settings: Settings,
    ) -> None:
        """Startup username sync must rewrite canonical post authors before cache rebuild."""
        from unittest.mock import patch

        from backend.filesystem.content_manager import ContentManager
        from backend.services.cache_service import ensure_tables, rebuild_cache
        from backend.services.post_service import list_posts

        def _write_post(post_path) -> None:
            post_path.parent.mkdir(parents=True, exist_ok=True)
            post_path.write_text(
                "---\n"
                "title: Legacy Post\n"
                "author: legacy-admin\n"
                "created_at: 2026-01-01 12:00:00+00:00\n"
                "modified_at: 2026-01-01 12:00:00+00:00\n"
                "---\n"
                "Hello\n",
                encoding="utf-8",
            )

        legacy_admin = await _create_user(
            session,
            username="legacy-admin",
            password="legacy-password",
        )
        assert legacy_admin.username == "legacy-admin"

        post_path = tmp_content_dir / "posts" / "legacy-post" / "index.md"
        _write_post(post_path)

        test_settings.admin_username = "configured-admin"
        test_settings.admin_password = "configured-password"
        test_settings.admin_display_name = "Configured Admin"

        await ensure_tables(session)
        content_manager = ContentManager(tmp_content_dir)

        async def _stub_render(markdown: str) -> str:
            return f"<p>{markdown}</p>"

        with (
            patch("backend.services.cache_service.render_markdown", side_effect=_stub_render),
            patch(
                "backend.services.cache_service.render_markdown_excerpt",
                side_effect=_stub_render,
            ),
        ):
            await ensure_admin_user(session, test_settings, content_manager=content_manager)
            await rebuild_cache(db_session_factory, content_manager)

        content = post_path.read_text(encoding="utf-8")
        assert "author: configured-admin" in content
        assert "author: legacy-admin" not in content

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author == "Configured Admin"

    @pytest.mark.asyncio
    async def test_collapses_duplicate_admin_rows_to_single_configured_identity(
        self, session: AsyncSession, test_settings: Settings
    ) -> None:
        """Multiple admin rows must converge to exactly one configured account."""
        stale_admin = await _create_user(session, username="stale-admin", password="stale-password")
        _, stale_refresh = await create_tokens(session, stale_admin, test_settings)
        configured_admin = await _create_user(
            session,
            username=test_settings.admin_username,
            password="old-configured-password",
        )
        _, configured_refresh = await create_tokens(session, configured_admin, test_settings)

        test_settings.admin_password = "rotated-configured-password"

        await ensure_admin_user(session, test_settings)

        result = await session.execute(select(AdminUser).order_by(AdminUser.id))
        admins = list(result.scalars().all())
        assert len(admins) == 1

        admin = admins[0]
        assert admin.id == configured_admin.id
        assert admin.username == test_settings.admin_username
        assert await session.get(AdminUser, stale_admin.id) is None
        assert await authenticate_admin(session, "stale-admin", "stale-password") is None

        authed = await authenticate_admin(
            session, test_settings.admin_username, "rotated-configured-password"
        )
        assert authed is not None
        assert authed.id == configured_admin.id

        refresh_result = await session.execute(
            select(AdminRefreshToken).where(
                AdminRefreshToken.token_hash.in_(
                    [hash_token(stale_refresh), hash_token(configured_refresh)]
                )
            )
        )
        assert list(refresh_result.scalars().all()) == []

    @pytest.mark.asyncio
    async def test_rewrites_existing_post_authors_for_stale_admin_rows(
        self,
        session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
        test_settings: Settings,
    ) -> None:
        """Configured-admin bootstrap must rewrite posts authored by stale admin rows."""
        from backend.services.cache_service import ensure_tables, rebuild_cache
        from backend.services.post_service import list_posts

        configured_admin = await _create_user(
            session,
            username=test_settings.admin_username,
            password="configured-password",
        )
        await _create_user(
            session,
            username="stale-admin",
            password="stale-password",
        )
        assert configured_admin.username == test_settings.admin_username

        post_path = tmp_content_dir / "posts" / "stale-post" / "index.md"
        post_path.parent.mkdir(parents=True, exist_ok=True)
        post_path.write_text(
            "---\n"
            "title: Stale Post\n"
            "author: stale-admin\n"
            "created_at: 2026-01-01 12:00:00+00:00\n"
            "modified_at: 2026-01-01 12:00:00+00:00\n"
            "---\n"
            "Hello\n",
            encoding="utf-8",
        )

        await ensure_tables(session)
        content_manager = ContentManager(tmp_content_dir)

        async def _stub_render(markdown: str) -> str:
            return f"<p>{markdown}</p>"

        with (
            patch("backend.services.cache_service.render_markdown", side_effect=_stub_render),
            patch(
                "backend.services.cache_service.render_markdown_excerpt",
                side_effect=_stub_render,
            ),
        ):
            await ensure_admin_user(session, test_settings, content_manager=content_manager)
            await rebuild_cache(db_session_factory, content_manager)

        content = post_path.read_text(encoding="utf-8")
        assert "author: admin" in content
        assert "author: stale-admin" not in content

        admin_result = await session.execute(select(AdminUser).order_by(AdminUser.id))
        admins = list(admin_result.scalars().all())
        assert len(admins) == 1
        assert admins[0].id == configured_admin.id

        result = await list_posts(session)
        assert len(result.posts) == 1
        assert result.posts[0].author == "admin"


# ---------------------------------------------------------------------------
# C1: Narrow bare except on password sync
# ---------------------------------------------------------------------------


class TestEnsureAdminUserPasswordSyncExceptions:
    """ensure_admin_user must narrow exception handling on password sync."""

    @pytest.mark.asyncio
    async def test_value_error_in_verify_password_is_caught_and_logged(
        self,
        session: AsyncSession,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ValueError from verify_password must be caught, logged, and not crash."""
        await ensure_admin_user(session, test_settings)

        def _raise_value_error(plain: str, hashed: str) -> bool:
            raise ValueError("bad hash format")

        monkeypatch.setattr("backend.services.auth_service.verify_password", _raise_value_error)

        with caplog.at_level(logging.ERROR, logger="backend.services.auth_service"):
            # Must not raise
            await ensure_admin_user(session, test_settings)

        assert any("password" in record.message.lower() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_runtime_error_in_verify_password_propagates(
        self,
        session: AsyncSession,
        test_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RuntimeError from verify_password must NOT be silently swallowed."""
        await ensure_admin_user(session, test_settings)

        def _raise_runtime_error(plain: str, hashed: str) -> bool:
            raise RuntimeError("unexpected native library failure")

        monkeypatch.setattr("backend.services.auth_service.verify_password", _raise_runtime_error)

        with pytest.raises(RuntimeError, match="unexpected native library failure"):
            await ensure_admin_user(session, test_settings)


# ---------------------------------------------------------------------------
# I5: Add logging for unparseable expires_at
# ---------------------------------------------------------------------------


class TestRefreshTokensUnparseableExpiresAt:
    """refresh_tokens must warn when expires_at is unparseable."""

    @pytest.mark.asyncio
    async def test_unparseable_expires_at_logs_warning(
        self,
        session: AsyncSession,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A stored token with an unparseable expires_at must trigger a warning log."""
        user = await _create_user(session, username="expires-user")
        # Insert a refresh token with a bad expires_at directly
        from backend.services.auth_service import create_refresh_token_value, hash_token

        token_value = create_refresh_token_value()
        token_hash = hash_token(token_value)
        now = format_iso(now_utc())
        bad_token = AdminRefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at="not-a-date",
            created_at=now,
        )
        session.add(bad_token)
        await session.commit()

        with caplog.at_level(logging.WARNING, logger="backend.services.auth_service"):
            result = await refresh_tokens(session, token_value, test_settings)

        assert result is None
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "unparseable" in r.message.lower()
        ]
        assert len(warning_records) >= 1
        assert all("not-a-date" not in record.message for record in warning_records)
        assert all(str(bad_token.id) not in record.message for record in warning_records)


# ---------------------------------------------------------------------------
# S1: Log InvalidKeyError at error level
# ---------------------------------------------------------------------------


class TestDecodeAccessTokenInvalidKeyError:
    """InvalidKeyError must raise InternalServerError and be logged at ERROR level."""

    def test_invalid_key_error_raises_and_logs_at_error_level(
        self,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A token that triggers InvalidKeyError must raise InternalServerError and log at ERROR."""
        # Simulate jwt.decode raising InvalidKeyError (server misconfiguration scenario)
        token = create_access_token({"sub": "1", "username": "alice"}, test_settings.secret_key)

        def _raise_invalid_key(*args: object, **kwargs: object) -> dict[str, object]:
            raise jwt.InvalidKeyError("key mismatch — simulated misconfiguration")

        monkeypatch.setattr(jwt, "decode", _raise_invalid_key)

        with (
            caplog.at_level(logging.DEBUG, logger="backend.services.auth_service"),
            pytest.raises(InternalServerError),
        ):
            decode_access_token(token, test_settings.secret_key)

        error_records = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR and "signing key" in r.message.lower()
        ]
        assert len(error_records) >= 1


# ---------------------------------------------------------------------------
# S2: Contextual error handling for _collapse_admin_identities
# ---------------------------------------------------------------------------


class TestCollapseAdminIdentitiesErrorHandling:
    """ensure_admin_user must log and re-raise exceptions from _collapse_admin_identities."""

    @pytest.mark.asyncio
    async def test_integrity_error_is_logged_and_reraised(
        self,
        session: AsyncSession,
        test_settings: Settings,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IntegrityError from _collapse_admin_identities is logged and re-raised."""
        # Create a stale admin so the collapse path is taken
        stale_admin = await _create_user(session, username="stale-for-collapse")
        # Create the configured admin separately so there are two admins
        configured_admin = await _create_user(
            session,
            username=test_settings.admin_username,
            password=test_settings.admin_password,
        )
        assert stale_admin.id != configured_admin.id

        import backend.services.auth_service as auth_mod

        async def _raise_integrity_error(
            _session: AsyncSession,
            *,
            target: AdminUser,
            stale_admins: list[AdminUser],
        ) -> None:
            raise IntegrityError("simulated", {}, Exception())

        monkeypatch.setattr(auth_mod, "_collapse_admin_identities", _raise_integrity_error)

        with (
            caplog.at_level(logging.CRITICAL, logger="backend.services.auth_service"),
            pytest.raises(IntegrityError),
        ):
            await ensure_admin_user(session, test_settings)

        critical_records = [
            r
            for r in caplog.records
            if r.levelno == logging.CRITICAL and "collapse" in r.message.lower()
        ]
        assert len(critical_records) >= 1


class TestDecodeAccessTokenInvalidKey:
    """decode_access_token raises InternalServerError on jwt.InvalidKeyError (S-02)."""

    def test_invalid_key_error_raises_internal_server_error(self, test_settings: Settings) -> None:
        """InvalidKeyError must raise InternalServerError, not silently return None."""
        token = create_access_token(
            {"sub": "1", "username": "alice"},
            test_settings.secret_key,
        )
        with patch("backend.services.auth_service.jwt.decode") as mock_decode:
            mock_decode.side_effect = jwt.InvalidKeyError("key mismatch")
            with pytest.raises(InternalServerError):
                decode_access_token(token, test_settings.secret_key)

    def test_invalid_key_error_logged_at_error_with_secret_key_hint(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        """InvalidKeyError must be logged at ERROR level mentioning SECRET_KEY."""
        token = create_access_token(
            {"sub": "1", "username": "alice"},
            test_settings.secret_key,
        )
        with (
            patch("backend.services.auth_service.jwt.decode") as mock_decode,
            caplog.at_level(logging.ERROR, logger="backend.services.auth_service"),
            pytest.raises(InternalServerError),
        ):
            mock_decode.side_effect = jwt.InvalidKeyError("key mismatch")
            decode_access_token(token, test_settings.secret_key)

        error_records = [
            r for r in caplog.records if r.levelno == logging.ERROR and "SECRET_KEY" in r.message
        ]
        assert len(error_records) >= 1


class TestCollapseAdminIdentities:
    """Tests for _collapse_admin_identities social account and cross-post migration."""

    @pytest.fixture
    async def _tables(self, db_engine: AsyncEngine) -> None:
        async with db_engine.begin() as conn:
            await conn.run_sync(DurableBase.metadata.create_all)

    @pytest.fixture
    async def session(self, db_session: AsyncSession, _tables: None) -> AsyncSession:
        return db_session

    async def _make_admin(self, session: AsyncSession, username: str) -> AdminUser:
        now = format_iso(now_utc())
        user = AdminUser(
            username=username,
            email=f"{username}@test.local",
            password_hash=hash_password("pw"),
            display_name=username,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def _make_social_account(
        self, session: AsyncSession, user: AdminUser, platform: str, account_name: str = ""
    ) -> SocialAccount:
        now = format_iso(now_utc())
        sa = SocialAccount(
            user_id=user.id,
            platform=platform,
            account_name=account_name,
            credentials="{}",
            created_at=now,
            updated_at=now,
        )
        session.add(sa)
        await session.flush()
        await session.refresh(sa)
        return sa

    async def _make_cross_post(
        self, session: AsyncSession, user: AdminUser, post_path: str, platform: str
    ) -> CrossPost:
        now = format_iso(now_utc())
        cp = CrossPost(
            user_id=user.id,
            post_path=post_path,
            platform=platform,
            status=CrossPostStatus.POSTED,
            created_at=now,
        )
        session.add(cp)
        await session.flush()
        await session.refresh(cp)
        return cp

    @pytest.mark.asyncio
    async def test_social_accounts_reassigned_from_stale_to_target(
        self, session: AsyncSession
    ) -> None:
        """Social accounts on stale admin rows are reassigned to the target admin."""
        target = await self._make_admin(session, "target-admin")
        stale = await self._make_admin(session, "stale-admin")
        sa = await self._make_social_account(session, stale, "bluesky", "stale@bsky")

        await _collapse_admin_identities(session, target=target, stale_admins=[stale])
        await session.refresh(sa)

        assert sa.user_id == target.id

    @pytest.mark.asyncio
    async def test_duplicate_social_account_is_dropped(self, session: AsyncSession) -> None:
        """A social account that duplicates one already on the target is dropped (not moved)."""
        target = await self._make_admin(session, "target-dup")
        stale = await self._make_admin(session, "stale-dup")

        await self._make_social_account(session, target, "mastodon", "shared@mastodon")
        stale_sa = await self._make_social_account(session, stale, "mastodon", "shared@mastodon")

        await _collapse_admin_identities(session, target=target, stale_admins=[stale])

        result = await session.execute(select(SocialAccount).where(SocialAccount.id == stale_sa.id))
        assert result.scalar_one_or_none() is None

        result = await session.execute(
            select(SocialAccount).where(
                SocialAccount.user_id == target.id,
                SocialAccount.platform == "mastodon",
                SocialAccount.account_name == "shared@mastodon",
            )
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_cross_posts_reassigned_from_stale_to_target(self, session: AsyncSession) -> None:
        """CrossPost records on stale admin rows are reassigned to the target admin."""
        target = await self._make_admin(session, "target-cp")
        stale = await self._make_admin(session, "stale-cp")
        cp = await self._make_cross_post(session, stale, "posts/2026-01-01-test", "bluesky")

        await _collapse_admin_identities(session, target=target, stale_admins=[stale])
        await session.refresh(cp)

        assert cp.user_id == target.id


class TestUpdateAuthorInPostsPartialFailure:
    """update_author_in_posts must surface partial failure after attempting all writes."""

    def test_individual_write_failure_is_logged_and_processing_continues(
        self,
        tmp_content_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A single write failure must be logged, remaining posts attempted, and the call fail."""
        posts_dir = tmp_content_dir / "posts"

        for slug in ("post-a", "post-b", "post-c"):
            post_dir = posts_dir / slug
            post_dir.mkdir(parents=True, exist_ok=True)
            (post_dir / "index.md").write_text(
                f"---\ntitle: {slug}\nauthor: oldname\n"
                "created_at: 2026-01-01\nmodified_at: 2026-01-01\n---\nbody\n"
            )

        content_manager = ContentManager(content_dir=tmp_content_dir)

        call_count = 0
        original_write = content_manager.write_post

        def _failing_write(rel_path: str, post_data: PostData) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("disk full")
            original_write(rel_path, post_data)

        content_manager.write_post = _failing_write

        with (
            caplog.at_level(logging.ERROR, logger="backend.services.auth_service"),
            pytest.raises(OSError, match="Author update completed with errors"),
        ):
            update_author_in_posts(content_manager, "oldname", "newname")

        assert call_count == 3
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1

        updated_authors = 0
        stale_authors = 0
        for slug in ("post-a", "post-b", "post-c"):
            content = (posts_dir / slug / "index.md").read_text(encoding="utf-8")
            if "author: newname" in content:
                updated_authors += 1
            if "author: oldname" in content:
                stale_authors += 1
        assert updated_authors == 2
        assert stale_authors == 1

    def test_all_writes_fail_raises_oserror(
        self,
        tmp_content_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When all writes fail, the helper must raise so callers can abort or roll back."""
        posts_dir = tmp_content_dir / "posts"
        post_dir = posts_dir / "mypost"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "index.md").write_text(
            "---\ntitle: My Post\nauthor: oldname\n"
            "created_at: 2026-01-01\nmodified_at: 2026-01-01\n---\nbody\n"
        )

        content_manager = ContentManager(content_dir=tmp_content_dir)

        def _always_fails(rel_path: str, post_data: PostData) -> None:
            raise OSError("permission denied")

        content_manager.write_post = _always_fails

        with (
            caplog.at_level(logging.ERROR, logger="backend.services.auth_service"),
            pytest.raises(OSError, match="Author update completed with errors"),
        ):
            update_author_in_posts(content_manager, "oldname", "newname")

        assert any(r.levelno >= logging.ERROR for r in caplog.records)
        content = (post_dir / "index.md").read_text(encoding="utf-8")
        assert "author: oldname" in content
