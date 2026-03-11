"""Cross-posting service: manages social accounts and cross-posting operations."""

from __future__ import annotations

import json
import logging
from inspect import isawaitable
from typing import TYPE_CHECKING, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.crosspost.base import CrossPostContent, CrossPostResult
from backend.crosspost.registry import get_poster, list_platforms
from backend.exceptions import InternalServerError, PostNotFoundError
from backend.models.crosspost import CrossPost, SocialAccount
from backend.models.post import PostCache
from backend.schemas.crosspost import CrossPostStatus
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.services.datetime_service import format_datetime, now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.filesystem.content_manager import ContentManager
    from backend.models.user import User
    from backend.schemas.crosspost import SocialAccountCreate

logger = logging.getLogger(__name__)
T = TypeVar("T")


class DuplicateAccountError(ValueError):
    """Raised when a social account with the same user/platform/name already exists."""


async def _resolve_maybe_awaitable[T](value: T) -> T:
    """Resolve values returned by sync SQLAlchemy APIs or async test doubles."""
    if isawaitable(value):
        return cast("T", await value)
    return value


async def create_social_account(
    session: AsyncSession,
    user_id: int,
    data: SocialAccountCreate,
    secret_key: str,
) -> SocialAccount:
    """Create a new social account connection.

    Validates the platform name and stores credentials encrypted at rest.
    """
    available = list_platforms()
    if data.platform not in available:
        msg = f"Unsupported platform: {data.platform!r}"
        raise ValueError(msg)

    now = format_datetime(now_utc())
    encrypted_creds = encrypt_value(json.dumps(data.credentials), secret_key)
    account = SocialAccount(
        user_id=user_id,
        platform=data.platform,
        account_name=data.account_name,
        credentials=encrypted_creds,
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        msg = f"Account already exists for {data.platform}/{data.account_name}"
        raise DuplicateAccountError(msg) from exc
    await session.refresh(account)
    return account


async def get_social_accounts(
    session: AsyncSession,
    user_id: int,
) -> list[SocialAccount]:
    """List all social accounts for a user."""
    stmt = (
        select(SocialAccount)
        .where(SocialAccount.user_id == user_id)
        .order_by(SocialAccount.platform, SocialAccount.account_name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_social_account(
    session: AsyncSession,
    account_id: int,
    user_id: int,
) -> bool:
    """Delete a social account. Returns True if found and deleted."""
    stmt = select(SocialAccount).where(
        SocialAccount.id == account_id,
        SocialAccount.user_id == user_id,
    )
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        return False
    await session.delete(account)
    await session.commit()
    return True


async def crosspost(
    session: AsyncSession,
    content_manager: ContentManager,
    post_path: str,
    platforms: list[str],
    actor: User,
    site_url: str,
    secret_key: str = "",
    custom_text: str | None = None,
) -> list[CrossPostResult]:
    """Cross-post a blog post to the specified platforms.

    Reads the post from the content manager, builds CrossPostContent,
    then calls each platform poster. Errors are caught per-platform
    and recorded in the cross_posts table.
    """
    # Read the post
    post_data = content_manager.read_post(post_path)
    if post_data is None:
        msg = f"Post not found: {post_path}"
        raise PostNotFoundError(msg)

    post_stmt = select(PostCache).where(PostCache.file_path == post_path)
    post_query_result = await session.execute(post_stmt)
    cached_post = await _resolve_maybe_awaitable(post_query_result.scalar_one_or_none())

    is_draft = cached_post.is_draft if cached_post is not None else post_data.is_draft
    owner_username = cached_post.author if cached_post is not None else post_data.author
    if is_draft and not actor.is_admin and owner_username != actor.username:
        msg = f"Post not found: {post_path}"
        raise PostNotFoundError(msg)

    # Build the post URL
    # Strip .md extension and leading posts/ for the URL slug
    slug = post_path
    if slug.startswith("posts/"):
        slug = slug.removeprefix("posts/")
    if slug.endswith(".md"):
        slug = slug.removesuffix(".md")
    post_url = f"{site_url.rstrip('/')}/posts/{slug}"

    excerpt = content_manager.get_plain_excerpt(post_data)
    content = CrossPostContent(
        title=post_data.title,
        excerpt=excerpt,
        url=post_url,
        labels=post_data.labels,
        custom_text=custom_text,
    )

    # Get user's social accounts
    stmt = select(SocialAccount).where(
        SocialAccount.user_id == actor.id,
        SocialAccount.platform.in_(platforms),
    )
    result = await session.execute(stmt)
    account_rows = await _resolve_maybe_awaitable(result.scalars().all())
    accounts: dict[str, SocialAccount] = {}
    for acct in account_rows:
        if acct.platform in accounts:
            logger.warning(
                "Multiple %s accounts found for user %d; using %s",
                acct.platform,
                actor.id,
                accounts[acct.platform].account_name,
            )
        else:
            accounts[acct.platform] = acct

    results: list[CrossPostResult] = []
    now = format_datetime(now_utc())

    for platform_name in platforms:
        account = accounts.get(platform_name)
        if account is None:
            # No account configured for this platform
            error_msg = f"No {platform_name} account configured"
            cp = CrossPost(
                user_id=actor.id,
                post_path=post_path,
                platform=platform_name,
                status=CrossPostStatus.FAILED,
                error=error_msg,
                created_at=now,
            )
            session.add(cp)
            results.append(
                CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=error_msg,
                )
            )
            continue

        try:
            credentials = json.loads(decrypt_value(account.credentials, secret_key))
        except InternalServerError:
            credentials = None
        except json.JSONDecodeError:
            credentials = None
        if credentials is None:
            logger.warning(
                "Failed to decrypt account data for %s account %s; "
                "stored credentials are unreadable",
                platform_name,
                account.account_name,
            )
            error_msg = (
                f"Credentials for {platform_name} are corrupted or unreadable. "
                "Please reconnect the account."
            )
            cp = CrossPost(
                user_id=actor.id,
                post_path=post_path,
                platform=platform_name,
                status=CrossPostStatus.FAILED,
                error=error_msg,
                created_at=now,
            )
            session.add(cp)
            results.append(
                CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=error_msg,
                )
            )
            continue
        try:
            poster = await get_poster(platform_name, credentials)
            publish_result = await poster.post(content)

            # Persist refreshed credentials if tokens were updated during posting
            get_updated = getattr(poster, "get_updated_credentials", None)
            if get_updated is not None:
                updated_creds: dict[str, str] | None = get_updated()
                if updated_creds is not None:
                    account.credentials = encrypt_value(json.dumps(updated_creds), secret_key)
                    account.updated_at = now
        except Exception as exc:
            logger.error("Cross-post to %s failed: %s", platform_name, exc, exc_info=True)
            publish_result = CrossPostResult(
                platform_id="",
                url="",
                success=False,
                error="Cross-posting failed",
            )

        # Record the result
        cp = CrossPost(
            user_id=actor.id,
            post_path=post_path,
            platform=platform_name,
            platform_id=publish_result.platform_id or None,
            status=CrossPostStatus.POSTED if publish_result.success else CrossPostStatus.FAILED,
            posted_at=now if publish_result.success else None,
            error=publish_result.error,
            created_at=now,
        )
        session.add(cp)
        results.append(publish_result)

    await session.commit()
    return results


async def get_crosspost_history(
    session: AsyncSession,
    post_path: str,
    user_id: int,
) -> list[CrossPost]:
    """Get cross-posting history for a specific post."""
    stmt = (
        select(CrossPost)
        .where(CrossPost.post_path == post_path, CrossPost.user_id == user_id)
        .order_by(CrossPost.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
