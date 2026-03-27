"""Authentication service: JWT tokens and password hashing."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import bcrypt
import jwt
from jwt import InvalidTokenError
from sqlalchemy import delete, select

from backend.models.user import AdminRefreshToken, AdminUser
from backend.services.datetime_service import format_iso, now_utc
from backend.services.key_derivation import derive_access_token_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.config import Settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"agblogger-dummy-password", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        logger.warning("Malformed password hash encountered during verification")
        return False


def create_access_token(data: dict[str, Any], secret_key: str, expires_minutes: int = 15) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = now_utc() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    signing_key = derive_access_token_key(secret_key)
    return str(jwt.encode(to_encode, signing_key, algorithm=ALGORITHM))


def create_refresh_token_value() -> str:
    """Generate a cryptographically secure refresh token."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Hash a token value (SHA-256) for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def decode_access_token(token: str, secret_key: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token."""
    try:
        signing_key = derive_access_token_key(secret_key)
        payload: dict[str, Any] = jwt.decode(token, signing_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Access token expired")
        return None
    except InvalidTokenError:
        logger.warning("Invalid access token", exc_info=True)
        return None


async def authenticate_admin(
    session: AsyncSession, username: str, password: str
) -> AdminUser | None:
    """Authenticate the admin by username and password."""
    stmt = select(AdminUser).where(AdminUser.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        # Run a dummy hash check to reduce username timing side channels.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_tokens(
    session: AsyncSession, user: AdminUser, settings: Settings
) -> tuple[str, str]:
    """Create access and refresh token pair for a user."""
    access_token = create_access_token(
        {"sub": str(user.id), "username": user.username},
        settings.secret_key,
        settings.access_token_expire_minutes,
    )

    refresh_token_value = create_refresh_token_value()
    token_hash = hash_token(refresh_token_value)
    now = now_utc()
    expires = now + timedelta(days=settings.refresh_token_expire_days)

    refresh_token = AdminRefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=format_iso(expires),
        created_at=format_iso(now),
    )
    session.add(refresh_token)
    await session.commit()

    return access_token, refresh_token_value


async def refresh_tokens(
    session: AsyncSession, refresh_token_value: str, settings: Settings
) -> tuple[str, str] | None:
    """Refresh an access token using a refresh token.

    Implements token rotation: old refresh token is revoked.
    """
    token_h = hash_token(refresh_token_value)
    stmt = select(AdminRefreshToken).where(AdminRefreshToken.token_hash == token_h)
    result = await session.execute(stmt)
    stored_token = result.scalar_one_or_none()

    if stored_token is None:
        return None

    expires = _parse_iso_datetime(stored_token.expires_at)
    if expires is None:
        await session.execute(
            delete(AdminRefreshToken).where(AdminRefreshToken.id == stored_token.id)
        )
        await session.commit()
        return None
    if expires < now_utc():
        await session.execute(
            delete(AdminRefreshToken).where(AdminRefreshToken.id == stored_token.id)
        )
        await session.commit()
        return None

    # Single-use guarantee under concurrency: only one caller can consume the token.
    delete_result = await session.execute(
        delete(AdminRefreshToken).where(
            AdminRefreshToken.id == stored_token.id,
            AdminRefreshToken.token_hash == token_h,
        )
    )
    if (getattr(delete_result, "rowcount", 0) or 0) != 1:
        logger.warning(
            "Session refresh already consumed (concurrent race or replay): id=%s",
            stored_token.id,
        )
        return None

    user = await session.get(AdminUser, stored_token.user_id)
    if user is None:
        await session.commit()
        return None

    return await create_tokens(session, user, settings)


async def revoke_refresh_token(session: AsyncSession, refresh_token_value: str) -> bool:
    """Revoke a refresh token. Returns True if a token was revoked."""
    token_h = hash_token(refresh_token_value)
    stmt = select(AdminRefreshToken).where(AdminRefreshToken.token_hash == token_h)
    result = await session.execute(stmt)
    token = result.scalar_one_or_none()
    if token is None:
        await session.commit()
        return False
    await session.delete(token)
    await session.commit()
    return True


async def revoke_user_credentials(session: AsyncSession, user_id: int) -> None:
    """Revoke all refresh tokens for a user.

    Caller must commit the session after calling this function.
    """
    await session.execute(delete(AdminRefreshToken).where(AdminRefreshToken.user_id == user_id))


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def ensure_admin_user(session: AsyncSession, settings: Settings) -> None:
    """Create or update the admin user to match environment configuration.

    On first run the admin is created.  On subsequent runs the password and
    display name are synced with the environment variables so that changing
    ``ADMIN_PASSWORD`` or ``ADMIN_DISPLAY_NAME`` takes effect on next restart.

    Note: the admin *username* is NOT updated on existing accounts.  If
    ``ADMIN_USERNAME`` is changed, a new admin account is created alongside
    the old one rather than the existing account being renamed.
    """
    stmt = select(AdminUser).where(AdminUser.username == settings.admin_username)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is None:
        now = format_iso(now_utc())
        admin = AdminUser(
            username=settings.admin_username,
            email=f"{settings.admin_username}@localhost",
            password_hash=hash_password(settings.admin_password),
            display_name=settings.admin_display_name.strip() or settings.admin_username,
            created_at=now,
            updated_at=now,
        )
        session.add(admin)
        await session.commit()
        return

    # Sync mutable fields with env config.
    dirty = False
    try:
        if not verify_password(settings.admin_password, existing.password_hash):
            existing.password_hash = hash_password(settings.admin_password)
            logger.info("Admin password updated to match ADMIN_PASSWORD environment variable")
            dirty = True
    except Exception:
        logger.error(
            "Failed to verify or update admin password hash — skipping password sync."
            " Fix the stored hash or restart with a clean database.",
            exc_info=True,
        )

    target_display = settings.admin_display_name.strip() or settings.admin_username
    if existing.display_name != target_display:
        existing.display_name = target_display
        dirty = True

    if dirty:
        existing.updated_at = format_iso(now_utc())
        await session.commit()
