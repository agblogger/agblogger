"""Authentication API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import (
    AsyncWriteLock,
    get_content_manager,
    get_content_write_lock,
    get_current_admin,
    get_session,
    get_session_factory,
    get_settings,
    require_admin,
)
from backend.config import Settings
from backend.filesystem.content_manager import ContentManager
from backend.models.user import AdminUser
from backend.schemas.auth import (
    CsrfTokenResponse,
    LoginRequest,
    LogoutRequest,
    ProfileUpdate,
    RefreshRequest,
    SessionAuthResponse,
    TokenResponse,
    UserResponse,
)
from backend.services.auth_service import (
    authenticate_admin,
    create_access_token,
    create_tokens,
    refresh_tokens,
    revoke_refresh_token,
)
from backend.services.csrf_service import create_csrf_token
from backend.services.datetime_service import format_iso, now_utc
from backend.services.rate_limit_service import InMemoryRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookies(
    response: Response,
    settings: Settings,
    access_token: str,
    refresh_token: str,
) -> str:
    secure = not settings.debug
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=settings.access_token_expire_minutes * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )
    return create_csrf_token(access_token, settings.secret_key)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("csrf_token", path="/")


def _is_trusted_proxy(client_ip: str, trusted_proxy_ips: list[str]) -> bool:
    """Check if a client IP matches any trusted proxy entry (exact IP or CIDR range)."""
    from backend.net_utils import is_trusted_proxy

    return is_trusted_proxy(client_ip, trusted_proxy_ips)


def _get_client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    client_host = request.client.host if request.client and request.client.host else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and _is_trusted_proxy(client_host, settings.trusted_proxy_ips):
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    if client_host:
        return client_host
    return "unknown"


def _origin_from_referer(referer: str) -> str | None:
    parsed = urlparse(referer)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _enforce_login_origin(request: Request, settings: Settings) -> None:
    """Reject cross-origin login attempts from untrusted browser origins."""
    origin = request.headers.get("Origin")
    if origin is None:
        referer = request.headers.get("Referer")
        if referer:
            origin = _origin_from_referer(referer)
    if origin is None:
        return
    request_origin = str(request.base_url).rstrip("/")
    allowed_origins = {request_origin, *settings.cors_origins}
    if origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Untrusted request origin",
        )


def _reject_browser_originated_token_login(request: Request) -> None:
    """Bearer token login is reserved for non-browser clients."""
    if request.headers.get("Origin") is not None or request.headers.get("Referer") is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Browser-originated requests must use session login",
        )


def _check_rate_limit(
    limiter: InMemoryRateLimiter,
    key: str,
    max_failures: int,
    window_seconds: int,
    detail: str,
) -> None:
    """Raise 429 if the key is rate-limited."""
    limited, retry_after = limiter.is_limited(key, max_failures, window_seconds)
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


def _record_failure_and_check(
    limiter: InMemoryRateLimiter,
    key: str,
    max_failures: int,
    window_seconds: int,
    detail: str,
) -> None:
    """Record a failed attempt and raise 429 if now rate-limited."""
    limiter.add_failure(key, window_seconds)
    _check_rate_limit(limiter, key, max_failures, window_seconds, detail)


async def _authenticate_login_request(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminUser:
    """Authenticate a login request with shared rate-limiting."""
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    client_key = f"login:{_get_client_ip(request)}:{body.username.lower()}"
    _check_rate_limit(
        limiter,
        client_key,
        settings.auth_login_max_failures,
        settings.auth_rate_limit_window_seconds,
        "Too many failed login attempts",
    )

    user = await authenticate_admin(session, body.username, body.password)
    if user is None:
        _record_failure_and_check(
            limiter,
            client_key,
            settings.auth_login_max_failures,
            settings.auth_rate_limit_window_seconds,
            "Too many failed login attempts",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    limiter.clear(client_key)
    return user


@router.post("/login", response_model=SessionAuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionAuthResponse:
    """Create a cookie-authenticated browser session."""
    if settings.auth_enforce_login_origin:
        _enforce_login_origin(request, settings)

    user = await _authenticate_login_request(body, request, session, settings)
    access_token, refresh_token = await create_tokens(session, user, settings)
    csrf_token = _set_auth_cookies(response, settings, access_token, refresh_token)
    return SessionAuthResponse(csrf_token=csrf_token)


@router.post("/token-login", response_model=TokenResponse)
async def token_login(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Issue a bearer access token for non-browser clients."""
    _reject_browser_originated_token_login(request)
    user = await _authenticate_login_request(body, request, session, settings)
    return TokenResponse(
        access_token=create_access_token(
            {"sub": str(user.id), "username": user.username},
            settings.secret_key,
            settings.access_token_expire_minutes,
        )
    )


@router.post("/refresh", response_model=SessionAuthResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: RefreshRequest | None = None,
) -> SessionAuthResponse:
    """Refresh access token using refresh token."""
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    client_key = f"refresh:{_get_client_ip(request)}"
    _check_rate_limit(
        limiter,
        client_key,
        settings.auth_refresh_max_failures,
        settings.auth_rate_limit_window_seconds,
        "Too many failed refresh attempts",
    )

    refresh_token = body.refresh_token if body is not None else None
    if refresh_token is None:
        refresh_token = request.cookies.get("refresh_token")
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    tokens = await refresh_tokens(session, refresh_token, settings)
    if tokens is None:
        _record_failure_and_check(
            limiter,
            client_key,
            settings.auth_refresh_max_failures,
            settings.auth_rate_limit_window_seconds,
            "Too many failed refresh attempts",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    limiter.clear(client_key)
    access_token, refresh_token = tokens
    csrf_token = _set_auth_cookies(response, settings, access_token, refresh_token)
    return SessionAuthResponse(csrf_token=csrf_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: LogoutRequest | None = None,
) -> Response:
    """Revoke refresh token and clear auth cookies."""
    refresh_token = body.refresh_token if body is not None else None
    if refresh_token is None:
        refresh_token = request.cookies.get("refresh_token")
    if refresh_token is not None:
        await revoke_refresh_token(session, refresh_token)
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/csrf", response_model=CsrfTokenResponse)
async def get_csrf_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CsrfTokenResponse:
    """Return the stateless CSRF token for the current cookie-authenticated session."""
    access_token = request.cookies.get("access_token")
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return CsrfTokenResponse(csrf_token=create_csrf_token(access_token, settings.secret_key))


@router.get("/me", response_model=UserResponse)
async def me(
    user: Annotated[AdminUser | None, Depends(get_current_admin)],
) -> UserResponse:
    """Get current user info."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return UserResponse.from_user(user)


def _update_author_in_posts(
    content_manager: ContentManager,
    old_username: str,
    new_username: str,
) -> int:
    """Update the author field in all markdown files that match old_username.

    Performs synchronous filesystem I/O for each matching post.
    Returns the number of posts updated.
    """
    posts = content_manager.scan_posts()
    updated = 0
    for post in posts:
        if post.author == old_username:
            post.author = new_username
            content_manager.write_post(post.file_path, post)
            updated += 1
    return updated


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AdminUser, Depends(require_admin)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> UserResponse:
    """Update current user's profile (username, display name).

    Username changes also update the author field in all markdown files
    on disk and trigger a full cache rebuild.
    """
    import asyncio

    from backend.services.cache_service import rebuild_cache

    changed = False
    needs_file_update = False
    old_username = user.username

    if body.username is not None and body.username != user.username:
        stmt = select(AdminUser).where(AdminUser.username == body.username)
        existing = await session.execute(stmt)
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )
        user.username = body.username
        changed = True
        needs_file_update = True

    if body.display_name is not None:
        new_display_name = body.display_name or None
        if new_display_name != user.display_name:
            user.display_name = new_display_name
            changed = True

    if changed:
        user.updated_at = format_iso(now_utc())
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            ) from None
        # Commit the user changes before any operation that needs its own session
        # (e.g. rebuild_cache), to avoid SQLite "database is locked" errors.
        await session.commit()
        await session.refresh(user)

    if needs_file_update:
        new_username = user.username
        logger.info(
            "Username change: %s -> %s, updating author in posts",
            old_username,
            new_username,
        )
        async with content_write_lock:
            try:
                count = await asyncio.to_thread(
                    _update_author_in_posts,
                    content_manager,
                    old_username,
                    new_username,
                )
                logger.info("Updated author in %d post(s)", count)
            except OSError as exc:
                logger.error(
                    "Failed to update author in posts: %s",
                    exc,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update author in post files",
                ) from exc
            try:
                await rebuild_cache(session_factory, content_manager)
            except Exception as exc:
                logger.error("Cache rebuild failed after author update, reverting files: %s", exc)
                try:
                    await asyncio.to_thread(
                        _update_author_in_posts,
                        content_manager,
                        new_username,
                        old_username,
                    )
                except OSError as revert_exc:
                    logger.error("Failed to revert author in posts: %s", revert_exc)
                # The user change was already committed, so session.rollback()
                # is a no-op. Use a fresh session to revert the username.
                try:
                    async with session_factory() as revert_session:
                        result = await revert_session.execute(
                            select(AdminUser).where(AdminUser.id == user.id)
                        )
                        db_user = result.scalar_one()
                        db_user.username = old_username
                        await revert_session.commit()
                except Exception as db_revert_exc:
                    logger.error("Failed to revert username in DB: %s", db_revert_exc)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update author",
                ) from exc

    return UserResponse.from_user(user)
