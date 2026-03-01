"""Content file serving endpoint."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_session, get_settings
from backend.config import Settings
from backend.models.post import PostCache
from backend.models.user import User

router = APIRouter(prefix="/api/content", tags=["content"])

_ALLOWED_PREFIXES = ("posts/", "assets/")


def _validate_path(file_path: str, content_dir: Path) -> Path:
    """Validate and resolve a content file path.

    Returns the resolved absolute path on success.
    Raises HTTPException on validation failure.
    """
    # Reject path traversal attempts
    if ".." in file_path.split("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed",
        )

    # Check allowed prefixes
    if not file_path.startswith(_ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this path is not allowed",
        )

    # Resolve the full path (follows symlinks)
    full_path = (content_dir / file_path).resolve()

    # Verify resolved path stays within the content directory
    if not full_path.is_relative_to(content_dir.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed",
        )

    return full_path


async def _check_draft_access(
    file_path: str,
    session: AsyncSession,
    user: User | None,
) -> None:
    """Deny access to files inside draft post directories.

    For files under ``posts/<dir>/``, look up the post whose ``file_path``
    starts with the same directory prefix.  If the post is a draft, only
    its author may access the file.
    """
    if not file_path.startswith("posts/"):
        return

    # Extract the directory component: "posts/<dir>/file" -> "posts/<dir>/"
    parts = file_path.split("/")
    if len(parts) < 3:
        # Flat post file under posts/, e.g. "posts/hello.md".
        stmt = select(PostCache).where(PostCache.file_path == file_path).limit(1)
    else:
        dir_prefix = "/".join(parts[:2]) + "/"
        # Find any post whose file_path lives in this directory.
        stmt = select(PostCache).where(PostCache.file_path.startswith(dir_prefix)).limit(1)

    result = await session.execute(stmt)
    post = result.scalar_one_or_none()

    if post is None or not post.is_draft:
        return

    # Draft post — require author match
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if post.author_username != user.username:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )


@router.get("/{file_path:path}")
async def serve_content_file(
    file_path: str,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_current_user)],
) -> FileResponse:
    """Serve a file from the content directory.

    Files under posts/ directories belonging to draft posts are restricted
    to the post's author. All other content is publicly accessible.
    """
    resolved = _validate_path(file_path, settings.content_dir)

    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # Check draft access for files under posts/ directories
    await _check_draft_access(file_path, session, user)

    # Determine content type
    content_type, _ = mimetypes.guess_type(str(resolved))
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(path=resolved, media_type=content_type)
