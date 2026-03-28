"""Authentication service: admin identity, credentials, JWT tokens, and refresh lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import bcrypt
import jwt
from jwt import InvalidTokenError
from sqlalchemy import delete, select

from backend.models.crosspost import CrossPost, SocialAccount
from backend.models.user import AdminRefreshToken, AdminUser
from backend.services.key_derivation import derive_access_token_key
from backend.utils.datetime import format_iso, now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.config import Settings
    from backend.filesystem.content_manager import ContentManager

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
    except jwt.InvalidKeyError:
        logger.error(
            "Access token validation failed due to invalid signing key — "
            "check SECRET_KEY server configuration",
            exc_info=True,
        )
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
    """Create access and refresh token pair for the admin."""
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
        logger.warning("Refresh token has unparseable expiration metadata, treating it as expired")
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


async def revoke_admin_credentials(session: AsyncSession, user_id: int) -> None:
    """Revoke all refresh tokens for the admin.

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


async def _collapse_admin_identities(
    session: AsyncSession,
    *,
    target: AdminUser,
    stale_admins: list[AdminUser],
) -> None:
    """Merge dependent state into ``target`` and delete stale admin rows."""
    if not stale_admins:
        return

    stale_ids = [admin.id for admin in stale_admins]

    target_accounts_result = await session.execute(
        select(SocialAccount).where(SocialAccount.user_id == target.id)
    )
    target_account_keys = {
        (account.platform, account.account_name)
        for account in target_accounts_result.scalars().all()
    }

    stale_accounts_result = await session.execute(
        select(SocialAccount)
        .where(SocialAccount.user_id.in_(stale_ids))
        .order_by(SocialAccount.id.asc())
    )
    for account in stale_accounts_result.scalars().all():
        key = (account.platform, account.account_name)
        if key in target_account_keys:
            logger.warning(
                "Dropping duplicate social account while collapsing stale admin id=%s",
                account.user_id,
            )
            await session.delete(account)
            continue
        account.user_id = target.id
        target_account_keys.add(key)

    stale_cross_posts_result = await session.execute(
        select(CrossPost).where(CrossPost.user_id.in_(stale_ids))
    )
    for cross_post in stale_cross_posts_result.scalars().all():
        cross_post.user_id = target.id

    for admin in stale_admins:
        await session.delete(admin)


def update_author_in_posts(
    content_manager: ContentManager,
    old_username: str,
    new_username: str,
) -> int:
    """Rewrite canonical post authors from ``old_username`` to ``new_username``.

    Returns the number of posts successfully updated.

    Individual write failures are logged at ERROR level but do not abort
    processing — remaining posts are always attempted.
    """
    posts = content_manager.scan_posts()
    updated = 0
    failed = 0
    for post in posts:
        if post.author == old_username:
            post.author = new_username
            try:
                content_manager.write_post(post.file_path, post)
                updated += 1
            except OSError as exc:
                failed += 1
                logger.error(
                    "Failed to update author in post file %s: %s",
                    post.file_path,
                    exc,
                )
    if failed:
        logger.error(
            "Author update completed with errors: %d updated, %d failed",
            updated,
            failed,
        )
    return updated


async def ensure_admin_user(
    session: AsyncSession,
    settings: Settings,
    *,
    content_manager: ContentManager | None = None,
) -> None:
    """Create or update the admin user to match environment configuration.

    On first run the admin is created.  On subsequent runs the password and
    display name are synced with the environment variables so that changing
    ``ADMIN_PASSWORD`` or ``ADMIN_DISPLAY_NAME`` takes effect on next restart.

    Startup also enforces the single-admin invariant. If stale admin rows are
    present from older configurations, the durable auth state is collapsed to
    the configured admin identity, stale refresh tokens are revoked, and when
    the configured username changes any canonical post authorship metadata is
    rewritten before the normal cache rebuild.
    """
    stmt = select(AdminUser).order_by(AdminUser.id.asc())
    result = await session.execute(stmt)
    admins = list(result.scalars().all())

    existing = next((admin for admin in admins if admin.username == settings.admin_username), None)
    stale_admins: list[AdminUser] = []
    identity_changed = False
    previous_username: str | None = None

    if existing is None:
        if admins:
            existing = admins[0]
            stale_admins = admins[1:]
            if existing.username != settings.admin_username:
                previous_username = existing.username
                logger.warning(
                    "Renaming admin id=%s from %r to configured username %r",
                    existing.id,
                    existing.username,
                    settings.admin_username,
                )
                existing.username = settings.admin_username
                identity_changed = True
        else:
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
    else:
        stale_admins = [admin for admin in admins if admin.id != existing.id]

    # Sync mutable fields with env config.
    dirty = False
    refresh_token_user_ids_to_revoke: set[int] = set()
    try:
        if not verify_password(settings.admin_password, existing.password_hash):
            existing.password_hash = hash_password(settings.admin_password)
            logger.info("Admin password updated to match ADMIN_PASSWORD environment variable")
            dirty = True
            refresh_token_user_ids_to_revoke.add(existing.id)
    except ValueError, OSError:
        logger.error(
            "Failed to verify or update admin password hash — skipping password sync."
            " Fix the stored hash or restart with a clean database.",
            exc_info=True,
        )

    target_display = settings.admin_display_name.strip() or settings.admin_username
    if existing.display_name != target_display:
        existing.display_name = target_display
        dirty = True

    if identity_changed:
        dirty = True
        refresh_token_user_ids_to_revoke.add(existing.id)

        if content_manager is not None and previous_username is not None:
            try:
                updated_posts = await asyncio.to_thread(
                    update_author_in_posts,
                    content_manager,
                    previous_username,
                    settings.admin_username,
                )
                logger.info(
                    "Updated author in %d post(s) during admin bootstrap username sync",
                    updated_posts,
                )
            except OSError:
                logger.error(
                    "Failed to update author in posts during admin bootstrap username sync",
                    exc_info=True,
                )
                raise

    if stale_admins:
        logger.warning(
            "Collapsing %d stale admin row(s) into configured admin id=%s",
            len(stale_admins),
            existing.id,
        )
        try:
            await _collapse_admin_identities(session, target=existing, stale_admins=stale_admins)
            refresh_token_user_ids_to_revoke.update(admin.id for admin in stale_admins)
            refresh_token_user_ids_to_revoke.add(existing.id)
        except Exception:
            logger.error(
                "Failed to collapse stale admin identities during startup",
                exc_info=True,
            )
            raise

    if refresh_token_user_ids_to_revoke:
        await session.execute(
            delete(AdminRefreshToken).where(
                AdminRefreshToken.user_id.in_(sorted(refresh_token_user_ids_to_revoke))
            )
        )

    if dirty:
        existing.updated_at = format_iso(now_utc())
    await session.commit()
