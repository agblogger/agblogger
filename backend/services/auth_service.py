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
from sqlalchemy import delete, select, update

from backend.exceptions import TokenExpiredError
from backend.models.user import InviteCode, PersonalAccessToken, RefreshToken, User
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
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
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
    except InvalidTokenError:
        logger.debug("Failed to decode access token", exc_info=True)
        return None


async def authenticate_user(session: AsyncSession, username: str, password: str) -> User | None:
    """Authenticate a user by username and password."""
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        # Run a dummy hash check to reduce username timing side channels.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_tokens(session: AsyncSession, user: User, settings: Settings) -> tuple[str, str]:
    """Create access and refresh token pair for a user."""
    access_token = create_access_token(
        {"sub": str(user.id), "username": user.username, "is_admin": user.is_admin},
        settings.secret_key,
        settings.access_token_expire_minutes,
    )

    refresh_token_value = create_refresh_token_value()
    token_hash = hash_token(refresh_token_value)
    now = now_utc()
    expires = now + timedelta(days=settings.refresh_token_expire_days)

    refresh_token = RefreshToken(
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
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_h)
    result = await session.execute(stmt)
    stored_token = result.scalar_one_or_none()

    if stored_token is None:
        return None

    expires = _parse_iso_datetime(stored_token.expires_at)
    if expires is None:
        await session.execute(delete(RefreshToken).where(RefreshToken.id == stored_token.id))
        await session.commit()
        return None
    if expires < datetime.now(UTC):
        await session.execute(delete(RefreshToken).where(RefreshToken.id == stored_token.id))
        await session.commit()
        return None

    # Single-use guarantee under concurrency: only one caller can consume the token.
    delete_result = await session.execute(
        delete(RefreshToken).where(
            RefreshToken.id == stored_token.id,
            RefreshToken.token_hash == token_h,
        )
    )
    if (getattr(delete_result, "rowcount", 0) or 0) != 1:
        logger.warning(
            "Session refresh already consumed (concurrent race or replay): id=%s",
            stored_token.id,
        )
        return None

    user = await session.get(User, stored_token.user_id)
    if user is None:
        await session.commit()
        return None

    return await create_tokens(session, user, settings)


async def revoke_refresh_token(session: AsyncSession, refresh_token_value: str) -> bool:
    """Revoke a refresh token. Returns True if a token was revoked."""
    token_h = hash_token(refresh_token_value)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_h)
    result = await session.execute(stmt)
    token = result.scalar_one_or_none()
    if token is None:
        await session.commit()
        return False
    await session.delete(token)
    await session.commit()
    return True


async def revoke_user_credentials(session: AsyncSession, user_id: int) -> None:
    """Revoke all refresh tokens and personal access tokens for a user.

    Caller must commit the session after calling this function.
    """
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    await session.execute(
        update(PersonalAccessToken)
        .where(
            PersonalAccessToken.user_id == user_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=format_iso(now_utc()))
    )


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def create_invite_code(
    session: AsyncSession,
    created_by_user_id: int,
    expires_days: int,
) -> tuple[InviteCode, str]:
    """Create and persist a single-use invite code."""
    now = now_utc()
    plaintext_code = f"aginvite_{secrets.token_urlsafe(24)}"
    invite = InviteCode(
        code_hash=hash_token(plaintext_code),
        created_by_user_id=created_by_user_id,
        created_at=format_iso(now),
        expires_at=format_iso(now + timedelta(days=expires_days)),
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return invite, plaintext_code


async def get_valid_invite_code(
    session: AsyncSession,
    invite_code: str,
) -> InviteCode | None:
    """Return invite if valid (exists, not used, not expired)."""
    stmt = select(InviteCode).where(InviteCode.code_hash == hash_token(invite_code))
    result = await session.execute(stmt)
    invite = result.scalar_one_or_none()
    if invite is None or invite.used_at is not None:
        return None
    expires = _parse_iso_datetime(invite.expires_at)
    if expires is None or expires <= now_utc():
        return None
    return invite


async def consume_invite_code(
    session: AsyncSession,
    *,
    invite_id: int,
    used_by_user_id: int,
    used_at: str,
) -> bool:
    """Atomically mark an invite as used exactly once.

    Returns True iff this call consumed the invite. Returns False when the invite
    was already consumed by another concurrent request.
    """
    result = await session.execute(
        update(InviteCode)
        .where(
            InviteCode.id == invite_id,
            InviteCode.used_at.is_(None),
        )
        .values(used_at=used_at, used_by_user_id=used_by_user_id)
    )
    consumed = (getattr(result, "rowcount", 0) or 0) == 1
    if not consumed:
        logger.warning(
            "Invite code already consumed (concurrent race): invite_id=%s",
            invite_id,
        )
    return consumed


def create_personal_access_token_value() -> str:
    """Generate a long-lived personal access token value."""
    return f"agpat_{secrets.token_urlsafe(48)}"


async def create_personal_access_token(
    session: AsyncSession,
    user_id: int,
    name: str,
    expires_days: int | None,
) -> tuple[PersonalAccessToken, str]:
    """Create and persist a personal access token."""
    now = now_utc()
    token_value = create_personal_access_token_value()
    expires_at = (
        format_iso(now + timedelta(days=expires_days)) if expires_days is not None else None
    )
    pat = PersonalAccessToken(
        user_id=user_id,
        name=name,
        token_hash=hash_token(token_value),
        created_at=format_iso(now),
        expires_at=expires_at,
    )
    session.add(pat)
    await session.commit()
    await session.refresh(pat)
    return pat, token_value


async def list_personal_access_tokens(
    session: AsyncSession,
    user_id: int,
) -> list[PersonalAccessToken]:
    """List active and historical personal access tokens for a user."""
    stmt = (
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id)
        .order_by(PersonalAccessToken.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def revoke_personal_access_token(
    session: AsyncSession,
    user_id: int,
    token_id: int,
) -> bool:
    """Revoke a personal access token owned by the user."""
    stmt = select(PersonalAccessToken).where(
        PersonalAccessToken.id == token_id,
        PersonalAccessToken.user_id == user_id,
    )
    result = await session.execute(stmt)
    pat = result.scalar_one_or_none()
    if pat is None:
        return False
    if pat.revoked_at is None:
        pat.revoked_at = format_iso(now_utc())
    await session.commit()
    return True


async def authenticate_personal_access_token(
    session: AsyncSession,
    token_value: str,
) -> User | None:
    """Authenticate a user with a personal access token."""
    stmt = select(PersonalAccessToken).where(
        PersonalAccessToken.token_hash == hash_token(token_value)
    )
    result = await session.execute(stmt)
    pat = result.scalar_one_or_none()
    if pat is None or pat.revoked_at is not None:
        return None

    if pat.expires_at is not None:
        expires = _parse_iso_datetime(pat.expires_at)
        if expires is None or expires <= now_utc():
            pat.revoked_at = format_iso(now_utc())
            await session.commit()
            raise TokenExpiredError("Personal access token expired")

    user = await session.get(User, pat.user_id)
    if user is None:
        return None

    pat.last_used_at = format_iso(now_utc())
    await session.commit()
    return user


async def ensure_admin_user(session: AsyncSession, settings: Settings) -> None:
    """Create the admin user if it doesn't exist."""
    stmt = select(User).where(User.username == settings.admin_username)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is None:
        now = format_iso(now_utc())
        admin = User(
            username=settings.admin_username,
            email=f"{settings.admin_username}@localhost",
            password_hash=hash_password(settings.admin_password),
            display_name="Admin",
            is_admin=True,
            created_at=now,
            updated_at=now,
        )
        session.add(admin)
        await session.commit()
