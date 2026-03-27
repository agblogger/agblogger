"""Shared API dependencies: DB session, auth, content manager, content write lock."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import Settings
from backend.filesystem.content_manager import ContentManager
from backend.models.user import AdminUser
from backend.services.auth_service import decode_access_token
from backend.services.git_service import GitService

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def set_git_warning(response: Response, commit_hash: str | None) -> None:
    """Set X-Git-Warning header when a git commit was expected but failed."""
    if commit_hash is None:
        response.headers["X-Git-Warning"] = "Git commit failed; changes saved but not versioned"


class AsyncWriteLock(Protocol):
    """Structural type for async locks used with ``async with``."""

    async def __aenter__(self) -> Any: ...

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> bool | None: ...


_SERVICE_UNAVAILABLE = "Service temporarily unavailable"
_DB_UNAVAILABLE = "Database temporarily unavailable"


def _require_app_state(request: Request, attr: str, detail: str) -> Any:
    """Get a required attribute from app state, raising 503 if missing."""
    value = getattr(request.app.state, attr, None)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    return value


def get_settings(request: Request) -> Settings:
    """Get application settings from app state."""
    return cast(
        "Settings",
        _require_app_state(request, "settings", _SERVICE_UNAVAILABLE),
    )


def get_git_service(request: Request) -> GitService:
    """Get git service from app state."""
    return cast(
        "GitService",
        _require_app_state(request, "git_service", _SERVICE_UNAVAILABLE),
    )


def get_content_manager(request: Request) -> ContentManager:
    """Get content manager from app state."""
    return cast(
        "ContentManager",
        _require_app_state(request, "content_manager", _SERVICE_UNAVAILABLE),
    )


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Get a database session."""
    session_factory = _require_app_state(
        request,
        "session_factory",
        _DB_UNAVAILABLE,
    )
    async with session_factory() as session:
        yield session


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Get the database session factory for operations that need their own session."""
    return cast(
        "async_sessionmaker[AsyncSession]",
        _require_app_state(request, "session_factory", _DB_UNAVAILABLE),
    )


def get_content_write_lock(request: Request) -> AsyncWriteLock:
    """Get the global content write lock used to serialize content mutations."""
    return cast(
        "AsyncWriteLock",
        _require_app_state(request, "content_write_lock", _SERVICE_UNAVAILABLE),
    )


async def get_current_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    session: AsyncSession = Depends(get_session),
) -> AdminUser | None:
    """Get current authenticated admin, or None if not authenticated."""
    token_value = (
        credentials.credentials if credentials is not None else request.cookies.get("access_token")
    )
    if token_value is None:
        return None

    settings: Settings = request.app.state.settings

    # Differentiate expired vs invalid/malformed tokens for logging.
    # decode_access_token handles its own logging (DEBUG for expired, WARNING for invalid),
    # but get_current_admin also catches the specific JWT exceptions to log at the deps level.
    import jwt as pyjwt

    from backend.services.key_derivation import derive_access_token_key

    try:
        signing_key = derive_access_token_key(settings.secret_key)
        pyjwt.decode(token_value, signing_key, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        logger.debug("Access token expired")
        return None
    except pyjwt.InvalidTokenError:
        logger.warning("Invalid access token")
        return None

    payload = decode_access_token(token_value, settings.secret_key)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        logger.warning("Access token missing sub claim")
        return None
    if not isinstance(user_id, (str, int)) or (isinstance(user_id, str) and not user_id.isdigit()):
        logger.warning("Access token missing sub claim")
        return None
    user = await session.get(AdminUser, int(user_id))
    if user is None:
        logger.warning("Access token references non-existent user id=%s", user_id)
    return user


async def require_admin(
    user: Annotated[AdminUser | None, Depends(get_current_admin)],
) -> AdminUser:
    """Require admin authentication. Raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
