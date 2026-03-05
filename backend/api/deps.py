"""Shared API dependencies: DB session, auth, content manager."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.filesystem.content_manager import ContentManager
from backend.models.user import User
from backend.services.auth_service import authenticate_personal_access_token, decode_access_token
from backend.services.git_service import GitService

security = HTTPBearer(auto_error=False)


class AsyncWriteLock(Protocol):
    """Structural type for async locks used with ``async with``."""

    async def __aenter__(self) -> Any: ...

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> bool | None: ...


def get_settings(request: Request) -> Settings:
    """Get application settings from app state."""
    settings: Settings = request.app.state.settings
    return settings


def get_git_service(request: Request) -> GitService:
    """Get git service from app state."""
    gs = getattr(request.app.state, "git_service", None)
    if gs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable",
        )
    return cast("GitService", gs)


def get_content_manager(request: Request) -> ContentManager:
    """Get content manager from app state."""
    cm = getattr(request.app.state, "content_manager", None)
    if cm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable",
        )
    return cast("ContentManager", cm)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Get a database session."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable",
        )
    async with session_factory() as session:
        yield session


def get_content_write_lock(request: Request) -> AsyncWriteLock:
    """Get the global content write lock used to serialize content mutations."""
    lock = getattr(request.app.state, "content_write_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        request.app.state.content_write_lock = lock
    return cast("AsyncWriteLock", lock)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Get current authenticated user, or None if not authenticated."""
    token_value = (
        credentials.credentials if credentials is not None else request.cookies.get("access_token")
    )
    if token_value is None:
        return None

    settings: Settings = request.app.state.settings
    payload = decode_access_token(token_value, settings.secret_key)
    if payload is not None:
        user_id = payload.get("sub")
        if user_id is None:
            return None
        if not isinstance(user_id, (str, int)) or (
            isinstance(user_id, str) and not user_id.isdigit()
        ):
            return None
        return await session.get(User, int(user_id))

    # PATs are supported for Bearer credentials only.
    if credentials is not None:
        return await authenticate_personal_access_token(session, token_value)
    return None


async def require_auth(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require authentication. Raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(require_auth)],
) -> User:
    """Require admin role. Raises 403 if not admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
