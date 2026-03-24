"""Content file serving endpoint."""

from __future__ import annotations

import logging
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
from backend.utils.slug import is_directory_post_path

router = APIRouter(prefix="/api/content", tags=["content"])

logger = logging.getLogger(__name__)

_ALLOWED_PREFIXES = ("posts/", "assets/")
_ATTACHMENT_MEDIA_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/pdf",
        "application/xhtml+xml",
        "application/xml",
        "image/svg+xml",
        "text/html",
        "text/javascript",
        "text/xml",
    }
)


def _validate_path(file_path: str, content_dir: Path) -> Path:
    """Validate and resolve a content file path.

    Returns the resolved absolute path on success.
    Raises HTTPException on validation failure.
    """
    # Reject path traversal attempts — return 404 (not 400/403) so the
    # response is indistinguishable from a genuinely missing file regardless
    # of whether the client used literal or URL-encoded traversal sequences.
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="File not found",
    )

    if ".." in file_path.split("/"):
        logger.warning("Path traversal attempt blocked: %s", file_path)
        raise not_found

    # Check allowed prefixes
    if not file_path.startswith(_ALLOWED_PREFIXES):
        logger.warning("Disallowed content prefix requested: %s", file_path)
        raise not_found

    # Resolve the full path (follows symlinks)
    full_path = (content_dir / file_path).resolve()

    # Verify resolved path stays within the content directory
    if not full_path.is_relative_to(content_dir.resolve()):
        logger.warning("Resolved path escapes content directory: %s", file_path)
        raise not_found

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

    Note: ``file_path`` should be the resolved (symlink-followed) relative
    path so that renamed post directories are matched correctly.
    """
    if not file_path.startswith("posts/"):
        return

    # For the canonical post path itself (posts/<slug>/index.md), do an exact
    # file_path lookup. For co-located assets (posts/<slug>/photo.png), use a
    # directory prefix lookup to find the owning post.
    parts = file_path.split("/")
    if is_directory_post_path(file_path):
        stmt = select(PostCache).where(PostCache.file_path == file_path).limit(1)
    else:
        dir_prefix = "/".join(parts[:2]) + "/"
        # Find any post whose file_path lives in this directory.
        stmt = select(PostCache).where(PostCache.file_path.startswith(dir_prefix)).limit(1)

    result = await session.execute(stmt)
    post = result.scalar_one_or_none()

    if post is None:
        return

    if not post.is_draft:
        return

    # Draft post — require author match
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if post.author != user.username:
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
    resolved_relative_path = resolved.relative_to(settings.content_dir.resolve()).as_posix()

    if (
        resolved_relative_path.startswith("posts/")
        and resolved_relative_path.endswith(".md")
        and not is_directory_post_path(resolved_relative_path)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # Check draft access for files under posts/ directories
    await _check_draft_access(resolved_relative_path, session, user)

    # Determine content type
    content_type, _ = mimetypes.guess_type(str(resolved))
    if content_type is None:
        content_type = "application/octet-stream"

    headers: dict[str, str] = {}
    filename = resolved.name
    if content_type in _ATTACHMENT_MEDIA_TYPES:
        # Escape backslashes and double-quotes in filename per RFC 6266
        safe_filename = filename.replace("\\", "\\\\").replace('"', '\\"')
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"

    return FileResponse(path=resolved, media_type=content_type, headers=headers)
