"""Authentication API endpoints."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_current_user,
    get_session,
    get_settings,
    require_admin,
    require_auth,
)
from backend.config import Settings
from backend.models.user import User
from backend.schemas.auth import (
    CsrfTokenResponse,
    InviteCreateRequest,
    InviteCreateResponse,
    LoginRequest,
    LogoutRequest,
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenCreateResponse,
    PersonalAccessTokenResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.services.auth_service import (
    authenticate_user,
    create_invite_code,
    create_personal_access_token,
    create_tokens,
    get_valid_invite_code,
    hash_password,
    list_personal_access_tokens,
    refresh_tokens,
    revoke_personal_access_token,
    revoke_refresh_token,
)
from backend.services.csrf_service import create_csrf_token
from backend.services.datetime_service import format_iso, now_utc
from backend.services.rate_limit_service import InMemoryRateLimiter

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


def _get_client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    client_host = request.client.host if request.client and request.client.host else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and client_host in settings.trusted_proxy_ips:
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


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Login with username and password."""
    if settings.auth_enforce_login_origin:
        _enforce_login_origin(request, settings)

    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    client_key = f"login:{_get_client_ip(request)}:{body.username.lower()}"
    _check_rate_limit(
        limiter,
        client_key,
        settings.auth_login_max_failures,
        settings.auth_rate_limit_window_seconds,
        "Too many failed login attempts",
    )

    user = await authenticate_user(session, body.username, body.password)
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
            detail="Invalid username or password",
        )

    limiter.clear(client_key)
    access_token, refresh_token = await create_tokens(session, user, settings)
    csrf_token = _set_auth_cookies(response, settings, access_token, refresh_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    """Register a new user account."""
    invite = None
    if not settings.auth_self_registration:
        if not settings.auth_invites_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled",
            )
        if body.invite_code is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invite code required",
            )
        invite = await get_valid_invite_code(session, body.invite_code)
        if invite is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired invite code",
            )

    existing = await session.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )

    now = format_iso(now_utc())
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        is_admin=False,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        ) from None

    if invite is not None:
        invite.used_at = now
        invite.used_by_user_id = user.id

    await session.commit()
    await session.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: RefreshRequest | None = None,
) -> TokenResponse:
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
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
    )


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
    user: Annotated[User | None, Depends(get_current_user)],
) -> UserResponse:
    """Get current user info."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


@router.post("/invites", response_model=InviteCreateResponse, status_code=201)
async def create_invite(
    body: InviteCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_user: Annotated[User, Depends(require_admin)],
) -> InviteCreateResponse:
    """Create a single-use invite code."""
    if not settings.auth_invites_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invites are disabled",
        )
    expires_days = body.expires_days or settings.auth_invite_expire_days
    invite, invite_code = await create_invite_code(session, admin_user.id, expires_days)
    return InviteCreateResponse(
        invite_code=invite_code,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


@router.post("/pats", response_model=PersonalAccessTokenCreateResponse, status_code=201)
async def create_pat(
    body: PersonalAccessTokenCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> PersonalAccessTokenCreateResponse:
    """Create a personal access token for API/CLI usage."""
    pat, token_value = await create_personal_access_token(
        session=session,
        user_id=user.id,
        name=body.name,
        expires_days=body.expires_days,
    )
    return PersonalAccessTokenCreateResponse(
        id=pat.id,
        name=pat.name,
        created_at=pat.created_at,
        expires_at=pat.expires_at,
        last_used_at=pat.last_used_at,
        revoked_at=pat.revoked_at,
        token=token_value,
    )


@router.get("/pats", response_model=list[PersonalAccessTokenResponse])
async def list_pats(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> list[PersonalAccessTokenResponse]:
    """List personal access tokens for the current user."""
    pats = await list_personal_access_tokens(session, user.id)
    return [
        PersonalAccessTokenResponse(
            id=pat.id,
            name=pat.name,
            created_at=pat.created_at,
            expires_at=pat.expires_at,
            last_used_at=pat.last_used_at,
            revoked_at=pat.revoked_at,
        )
        for pat in pats
    ]


@router.delete("/pats/{token_id}", status_code=204)
async def revoke_pat(
    token_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> Response:
    """Revoke a personal access token."""
    deleted = await revoke_personal_access_token(session, user.id, token_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )
    return Response(status_code=204)
