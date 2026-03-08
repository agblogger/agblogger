"""Post API endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path as FilePath
from typing import Annotated, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    AsyncWriteLock,
    get_content_manager,
    get_content_write_lock,
    get_current_user,
    get_git_service,
    get_session,
    require_admin,
    set_git_warning,
)
from backend.filesystem.content_manager import ContentManager, hash_content
from backend.filesystem.frontmatter import (
    PostData,
    generate_markdown_excerpt,
    serialize_post,
)
from backend.models.label import PostLabelCache
from backend.models.post import PostCache
from backend.models.user import User
from backend.pandoc.renderer import render_markdown, render_markdown_excerpt, rewrite_relative_urls
from backend.schemas.post import (
    AssetInfo,
    AssetListResponse,
    AssetRenameRequest,
    PostDetail,
    PostEditResponse,
    PostListResponse,
    PostSave,
    SearchResult,
)
from backend.services.datetime_service import format_iso, now_utc
from backend.services.git_service import GitService
from backend.services.label_service import ensure_label_cache_entry
from backend.services.post_service import get_post, list_posts, search_posts
from backend.services.slug_service import generate_post_path, generate_post_slug

logger = logging.getLogger(__name__)


async def _empty_string() -> str:
    """No-op coroutine returning empty string, for use as asyncio.gather placeholder."""
    return ""


router = APIRouter(prefix="/api/posts", tags=["posts"])

_FTS_DELETE_SQL = text(
    "INSERT INTO posts_fts(posts_fts, rowid, title, content) "
    "VALUES ('delete', :rowid, :title, :content)"
)

_FTS_INSERT_SQL = text(
    "INSERT INTO posts_fts(rowid, title, content) VALUES (:rowid, :title, :content)"
)


def _get_post_asset_directory(file_path: str, content_manager: ContentManager) -> FilePath:
    """Return the asset directory for a directory-backed post."""
    post_file = content_manager.content_dir / file_path
    if post_file.name != "index.md":
        msg = "Asset management requires a directory-style post ending in /index.md"
        raise HTTPException(status_code=400, detail=msg)
    return post_file.parent


async def _replace_post_labels(
    session: AsyncSession,
    *,
    post_id: int,
    labels: list[str],
) -> None:
    """Replace all cached label mappings for a post."""
    await session.execute(delete(PostLabelCache).where(PostLabelCache.post_id == post_id))
    for label_id in labels:
        await ensure_label_cache_entry(session, label_id)
        session.add(PostLabelCache(post_id=post_id, label_id=label_id))


async def _upsert_post_fts(
    session: AsyncSession,
    *,
    post_id: int,
    title: str,
    content: str,
    old_title: str | None = None,
    old_content: str | None = None,
) -> None:
    """Keep the full-text index row in sync with post cache mutations."""
    if old_title is not None and old_content is not None:
        await session.execute(
            _FTS_DELETE_SQL,
            {"rowid": post_id, "title": old_title, "content": old_content},
        )
    await session.execute(
        _FTS_INSERT_SQL,
        {"rowid": post_id, "title": title, "content": content},
    )


async def _delete_post_fts(
    session: AsyncSession, *, post_id: int, title: str, content: str
) -> None:
    """Delete a post row from the full-text index.

    If the exact content doesn't match what was originally inserted, the FTS delete
    silently fails. Orphaned entries are cleaned up on the next rebuild_cache().
    """
    try:
        await session.execute(
            _FTS_DELETE_SQL,
            {"rowid": post_id, "title": title, "content": content},
        )
    except OperationalError as exc:
        logger.warning(
            "FTS delete failed for post %d (will be cleaned up on next cache rebuild): %s",
            post_id,
            exc,
        )


async def _render_raw(content: str) -> tuple[str, str]:
    """Render excerpt and full HTML via Pandoc in parallel (no URL rewriting).

    Returns (raw_excerpt, raw_html).  Call ``rewrite_relative_urls`` on each
    result once the final ``file_path`` is known.
    """
    md_excerpt = generate_markdown_excerpt(content)

    raw_excerpt, raw_html = await asyncio.gather(
        render_markdown_excerpt(md_excerpt) if md_excerpt else _empty_string(),
        render_markdown(content),
    )
    return raw_excerpt, raw_html


def _build_post_detail(
    post: PostCache,
    *,
    labels: list[str],
    rendered_html: str,
    warnings: list[str] | None = None,
) -> PostDetail:
    """Build a PostDetail response from a cache row."""
    return PostDetail(
        id=post.id,
        file_path=post.file_path,
        title=post.title,
        author=post.author,
        created_at=format_iso(post.created_at),
        modified_at=format_iso(post.modified_at),
        is_draft=post.is_draft,
        rendered_excerpt=post.rendered_excerpt,
        labels=labels,
        rendered_html=rendered_html,
        warnings=warnings or [],
    )


@router.get("", response_model=PostListResponse)
async def list_posts_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    label: str | None = None,
    labels: str | None = None,
    label_mode: Literal["and", "or"] | None = Query(None, alias="labelMode"),
    author: str | None = None,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    sort: Literal["created_at", "modified_at", "title", "author"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
) -> PostListResponse:
    """List posts with pagination and filtering."""
    label_list = labels.split(",") if labels else None
    draft_owner_username = user.username if user else None
    try:
        return await list_posts(
            session,
            page=page,
            per_page=per_page,
            label=label,
            labels=label_list,
            label_mode=label_mode or "or",
            author=author,
            from_date=from_date,
            to_date=to_date,
            draft_owner_username=draft_owner_username,
            sort=sort,
            order=order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/search", response_model=list[SearchResult])
async def search_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[SearchResult]:
    """Full-text search for posts."""
    return await search_posts(session, q, limit=limit)


_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB per file
_MAX_TOTAL_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB total


@router.post("/upload", response_model=PostDetail, status_code=201)
async def upload_post(
    files: list[UploadFile],
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    user: Annotated[User, Depends(require_admin)],
    title: str | None = Query(None),
) -> PostDetail:
    """Upload a markdown post (single file or folder with assets).

    Accepts multipart files. One file must be a ``.md`` file (prefer ``index.md``
    if multiple). Applies the same YAML frontmatter normalization as the sync
    protocol: fills missing timestamps, author, and title.
    """
    file_data: list[tuple[str, bytes]] = []
    total_size = 0
    for upload_file in files:
        content = await upload_file.read()
        if len(content) > _MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {upload_file.filename}",
            )
        total_size += len(content)
        if total_size > _MAX_TOTAL_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Total upload size exceeds 50 MB limit",
            )
        filename = FilePath(upload_file.filename or "upload").name
        file_data.append((filename, content))

    md_files = [(name, data) for name, data in file_data if name.endswith(".md")]
    if not md_files:
        raise HTTPException(status_code=422, detail="No markdown file found in upload")

    is_directory_upload = len(file_data) > 1
    index_md = next(
        ((name, data) for name, data in md_files if name == "index.md"),
        None,
    )
    if is_directory_upload and index_md is None:
        raise HTTPException(
            status_code=422,
            detail="Directory upload must contain an index.md file",
        )
    md_file = index_md if index_md is not None else md_files[0]
    md_filename, md_bytes = md_file

    # Validate UTF-8 encoding
    try:
        raw_content = md_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File is not valid UTF-8 encoded text") from exc

    # Validate YAML front matter
    try:
        post_data = content_manager.read_post_from_string(raw_content, title_override=title)
    except (ValueError, yaml.YAMLError) as exc:
        logger.warning("Invalid front matter in uploaded file: %s", exc)
        raise HTTPException(
            status_code=422, detail="Invalid front matter in uploaded file"
        ) from exc

    if post_data.title == "Untitled" and title is None:
        raise HTTPException(status_code=422, detail="no_title")

    if not post_data.author:
        post_data.author = user.display_name or user.username
    post_data.author_username = user.username

    # Render via Pandoc before acquiring lock (the slow part)
    try:
        raw_excerpt, raw_html = await _render_raw(post_data.content)
    except (RuntimeError, OSError) as exc:
        logger.error("Pandoc rendering failed during upload: %s", exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc

    async with content_write_lock:
        posts_dir = content_manager.content_dir / "posts"
        post_path = generate_post_path(post_data.title, posts_dir)
        file_path = str(post_path.relative_to(content_manager.content_dir))
        post_data.file_path = file_path

        rendered_excerpt = rewrite_relative_urls(raw_excerpt, file_path)
        rendered_html = rewrite_relative_urls(raw_html, file_path)

        # Write asset files to directory
        post_dir = post_path.parent
        post_dir.mkdir(parents=True, exist_ok=True)
        written_assets: list[FilePath] = []
        for name, data in file_data:
            if name == md_filename:
                continue
            dest = post_dir / FilePath(name).name
            dest.write_bytes(data)
            written_assets.append(dest)

        serialized = serialize_post(post_data)
        post = PostCache(
            file_path=file_path,
            title=post_data.title,
            author=post_data.author,
            author_username=post_data.author_username,
            created_at=post_data.created_at,
            modified_at=post_data.modified_at,
            is_draft=post_data.is_draft,
            content_hash=hash_content(serialized),
            rendered_excerpt=rendered_excerpt,
            rendered_html=rendered_html,
        )
        session.add(post)
        await session.flush()
        await _replace_post_labels(session, post_id=post.id, labels=post_data.labels)
        await _upsert_post_fts(
            session,
            post_id=post.id,
            title=post_data.title,
            content=post_data.content,
        )

        try:
            content_manager.write_post(file_path, post_data)
        except OSError as exc:
            logger.error("Failed to write uploaded post %s: %s", file_path, exc)
            for asset in written_assets:
                asset.unlink(missing_ok=True)
            if post_dir.exists() and not any(post_dir.iterdir()):
                post_dir.rmdir()
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to write post file") from exc

        await session.commit()
        await session.refresh(post)
        set_git_warning(response, await git_service.try_commit(f"Upload post: {file_path}"))

        return _build_post_detail(post, labels=post_data.labels, rendered_html=rendered_html)


@router.get("/{file_path:path}/edit", response_model=PostEditResponse)
async def get_post_for_edit(
    file_path: str,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[User, Depends(require_admin)],
) -> PostEditResponse:
    """Get structured post data for the editor."""
    post_data = content_manager.read_post(file_path)
    if post_data is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return PostEditResponse(
        file_path=file_path,
        title=post_data.title,
        body=post_data.content,
        labels=post_data.labels,
        is_draft=post_data.is_draft,
        created_at=format_iso(post_data.created_at),
        modified_at=format_iso(post_data.modified_at),
        author=post_data.author,
    )


@router.post("/{file_path:path}/assets")
async def upload_assets(
    file_path: str,
    files: list[UploadFile],
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
) -> dict[str, list[str]]:
    """Upload asset files to a post's directory."""
    # Read all upload data before acquiring lock to avoid holding lock during I/O
    asset_data: list[tuple[str, bytes]] = []
    total_size = 0
    for upload_file in files:
        content = await upload_file.read()
        if len(content) > _MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {upload_file.filename}",
            )
        total_size += len(content)
        if total_size > _MAX_TOTAL_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="Total upload size exceeds 50 MB limit")
        filename = FilePath(upload_file.filename or "upload").name
        if not filename or filename.startswith("."):
            raise HTTPException(status_code=400, detail=f"Invalid filename: {upload_file.filename}")
        asset_data.append((filename, content))

    async with content_write_lock:
        # Verify post exists
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")

        post_dir = _get_post_asset_directory(file_path, content_manager)
        uploaded: list[str] = []
        for filename, data in asset_data:
            dest = post_dir / filename
            # Handle filesystem errors during asset write
            try:
                dest.write_bytes(data)
            except OSError as exc:
                logger.error("Failed to write asset %s: %s", dest, exc)
                raise HTTPException(
                    status_code=500, detail=f"Failed to write asset: {filename}"
                ) from exc
            uploaded.append(filename)

        if uploaded:
            commit_message = f"Upload assets to {file_path}: {', '.join(uploaded)}"
            set_git_warning(
                response,
                await git_service.try_commit(commit_message),
            )

        return {"uploaded": uploaded}


_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "avif"})


@router.get("/{file_path:path}/assets", response_model=AssetListResponse)
async def list_assets(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[User, Depends(require_admin)],
) -> AssetListResponse:
    """List asset files in a post's directory."""
    stmt = select(PostCache).where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Post not found")

    post_dir = _get_post_asset_directory(file_path, content_manager)
    assets: list[AssetInfo] = []
    try:
        for entry in sorted(post_dir.iterdir()):
            if entry.name == "index.md" or entry.name.startswith(".") or not entry.is_file():
                continue
            ext = entry.suffix.lstrip(".").lower()
            assets.append(
                AssetInfo(
                    name=entry.name,
                    size=entry.stat().st_size,
                    is_image=ext in _IMAGE_EXTENSIONS,
                )
            )
    except OSError as exc:
        logger.error("Failed to list assets for %s: %s", file_path, exc)
        raise HTTPException(status_code=500, detail="Failed to list assets") from exc

    return AssetListResponse(assets=assets)


def _validate_asset_filename(filename: str) -> None:
    """Validate an asset filename for safety."""
    if not filename or filename.startswith(".") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename}")
    if filename == "index.md":
        raise HTTPException(status_code=400, detail="Cannot modify the post content file")
    cleaned = FilePath(filename).name
    if cleaned != filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename}")


@router.delete("/{file_path:path}/assets/{filename}", status_code=204)
async def delete_asset(
    file_path: str,
    filename: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
) -> None:
    """Delete a single asset file from a post's directory."""
    _validate_asset_filename(filename)

    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Post not found")

        asset_path = _get_post_asset_directory(file_path, content_manager) / filename
        if not asset_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")

        try:
            asset_path.unlink()
        except OSError as exc:
            logger.error("Failed to delete asset %s: %s", asset_path, exc)
            raise HTTPException(status_code=500, detail="Failed to delete asset") from exc

        set_git_warning(
            response,
            await git_service.try_commit(f"Delete asset {filename} from {file_path}"),
        )


@router.patch("/{file_path:path}/assets/{filename}", response_model=AssetInfo)
async def rename_asset(
    file_path: str,
    filename: str,
    body: AssetRenameRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
) -> AssetInfo:
    """Rename an asset file in a post's directory."""
    _validate_asset_filename(filename)
    _validate_asset_filename(body.new_name)

    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Post not found")

        post_dir = _get_post_asset_directory(file_path, content_manager)
        old_path = post_dir / filename
        new_path = post_dir / body.new_name

        if not old_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        if new_path.exists():
            raise HTTPException(status_code=409, detail="A file with that name already exists")

        # Capture file size before rename — after rename, the old path is gone
        # and stat on the new path could fail due to transient filesystem issues.
        try:
            file_size = old_path.stat().st_size
        except OSError as exc:
            logger.warning("Failed to stat asset %s before rename: %s", old_path, exc)
            file_size = 0

        try:
            old_path.rename(new_path)
        except OSError as exc:
            logger.error("Failed to rename asset %s -> %s: %s", old_path, new_path, exc)
            raise HTTPException(status_code=500, detail="Failed to rename asset") from exc

        set_git_warning(
            response,
            await git_service.try_commit(
                f"Rename asset {filename} -> {body.new_name} in {file_path}"
            ),
        )

        ext = new_path.suffix.lstrip(".").lower()
        return AssetInfo(
            name=body.new_name,
            size=file_size,
            is_image=ext in _IMAGE_EXTENSIONS,
        )


@router.get("/{file_path:path}", response_model=PostDetail)
async def get_post_endpoint(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_current_user)],
) -> PostDetail:
    """Get a single post by file path."""
    post = await get_post(session, file_path)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.is_draft:
        if user is None:
            raise HTTPException(status_code=404, detail="Post not found")
        # PostDetail doesn't expose author_username; query the cache directly
        stmt = select(PostCache.author_username).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        author_username = result.scalar_one_or_none()
        if author_username != user.username:
            raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("", response_model=PostDetail, status_code=201)
async def create_post_endpoint(
    body: PostSave,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    user: Annotated[User, Depends(require_admin)],
) -> PostDetail:
    """Create a new post."""
    # Render via Pandoc before acquiring lock (the slow part)
    try:
        raw_excerpt, raw_html = await _render_raw(body.body)
    except (RuntimeError, OSError) as exc:
        logger.error("Pandoc rendering failed for new post: %s", exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc

    async with content_write_lock:
        posts_dir = content_manager.content_dir / "posts"
        post_path = generate_post_path(body.title, posts_dir)
        file_path = str(post_path.relative_to(content_manager.content_dir))

        existing = await session.execute(select(PostCache).where(PostCache.file_path == file_path))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="A post with this file path already exists")

        now = now_utc()
        author = user.display_name or user.username

        post_data = PostData(
            title=body.title,
            content=body.body,
            raw_content="",
            created_at=now,
            modified_at=now,
            author=author,
            author_username=user.username,
            labels=body.labels,
            is_draft=body.is_draft,
            file_path=file_path,
        )

        rendered_excerpt = rewrite_relative_urls(raw_excerpt, file_path)
        rendered_html = rewrite_relative_urls(raw_html, file_path)

        serialized = serialize_post(post_data)
        post = PostCache(
            file_path=file_path,
            title=post_data.title,
            author=post_data.author,
            author_username=post_data.author_username,
            created_at=post_data.created_at,
            modified_at=post_data.modified_at,
            is_draft=post_data.is_draft,
            content_hash=hash_content(serialized),
            rendered_excerpt=rendered_excerpt,
            rendered_html=rendered_html,
        )
        session.add(post)
        await session.flush()
        await _replace_post_labels(session, post_id=post.id, labels=body.labels)
        await _upsert_post_fts(
            session,
            post_id=post.id,
            title=post_data.title,
            content=post_data.content,
        )

        try:
            content_manager.write_post(file_path, post_data)
        except OSError as exc:
            logger.error("Failed to write post %s: %s", file_path, exc)
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to write post file") from exc

        await session.commit()
        await session.refresh(post)
        set_git_warning(response, await git_service.try_commit(f"Create post: {file_path}"))

        return _build_post_detail(post, labels=body.labels, rendered_html=rendered_html)


@router.put("/{file_path:path}", response_model=PostDetail)
async def update_post_endpoint(
    file_path: str,
    body: PostSave,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    user: Annotated[User, Depends(require_admin)],
) -> PostDetail:
    """Update an existing post."""
    # Render via Pandoc before acquiring lock (the slow part).
    # URL rewriting happens inside the lock once the final file_path is known.
    try:
        raw_rendered_excerpt, raw_rendered_html = await _render_raw(body.body)
    except (RuntimeError, OSError) as exc:
        logger.error("Pandoc rendering failed for post %s: %s", file_path, exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc

    endpoint_warnings: list[str] = []
    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="Post not found")

        # Read existing post to preserve created_at and author;
        # falls back to DB cache if file is missing
        existing_post_data = content_manager.read_post(file_path)
        if existing_post_data:
            created_at = existing_post_data.created_at
            author = existing_post_data.author
            author_username = existing_post_data.author_username or existing.author_username
        else:
            logger.warning(
                "Post %s exists in DB cache but not on filesystem; using cached metadata", file_path
            )
            created_at = existing.created_at
            author = existing.author or user.display_name or user.username
            author_username = existing.author_username

        now = now_utc()

        # Draft → published transition: update created_at to publish time
        if existing.is_draft and not body.is_draft:
            created_at = now

        title = body.title

        post_data = PostData(
            title=title,
            content=body.body,
            raw_content="",
            created_at=created_at,
            modified_at=now,
            author=author,
            author_username=author_username,
            labels=body.labels,
            is_draft=body.is_draft,
            file_path=file_path,
        )

        serialized = serialize_post(post_data)
        rendered_excerpt = rewrite_relative_urls(raw_rendered_excerpt, file_path)
        rendered_html = rewrite_relative_urls(raw_rendered_html, file_path)

        # Determine if rename is needed and rewrite URLs with new path BEFORE any
        # filesystem changes, so rename only happens after successful rendering.
        new_file_path = file_path
        new_rendered_excerpt = rendered_excerpt
        new_rendered_html = rendered_html
        needs_rename = False
        old_dir: FilePath | None = None
        new_dir: FilePath | None = None

        if file_path.endswith("/index.md"):
            new_slug = generate_post_slug(title)
            old_dir_name = FilePath(file_path).parent.name
            date_prefix_match = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", old_dir_name)
            if date_prefix_match:
                date_prefix = date_prefix_match.group(1)
                old_slug = date_prefix_match.group(2)
                if new_slug != old_slug:
                    old_dir = content_manager.content_dir / FilePath(file_path).parent
                    posts_parent = old_dir.parent
                    new_dir_name = f"{date_prefix}-{new_slug}"
                    new_dir = posts_parent / new_dir_name

                    # Handle collision: append -2, -3, etc.
                    if new_dir.exists():
                        counter = 2
                        while True:
                            candidate = posts_parent / f"{new_dir_name}-{counter}"
                            if not candidate.exists():
                                new_dir = candidate
                                break
                            counter += 1

                    new_file_path = str(
                        (new_dir / "index.md").relative_to(content_manager.content_dir)
                    )

                    # Rewrite URLs with new path (reuse already-rendered HTML)
                    new_rendered_excerpt = rewrite_relative_urls(
                        raw_rendered_excerpt, new_file_path
                    )
                    new_rendered_html = rewrite_relative_urls(raw_rendered_html, new_file_path)

                    needs_rename = True

        previous_title = existing.title
        previous_content = existing_post_data.content if existing_post_data else ""

        existing.title = title
        existing.author = author
        existing.author_username = author_username
        existing.created_at = created_at
        existing.modified_at = now
        existing.is_draft = body.is_draft
        existing.content_hash = hash_content(serialized)
        existing.rendered_excerpt = rendered_excerpt
        existing.rendered_html = rendered_html
        await _replace_post_labels(session, post_id=existing.id, labels=body.labels)
        await _upsert_post_fts(
            session,
            post_id=existing.id,
            title=title,
            content=post_data.content,
            old_title=previous_title,
            old_content=previous_content,
        )

        try:
            content_manager.write_post(file_path, post_data)
        except OSError as exc:
            logger.error("Failed to write post %s: %s", file_path, exc)
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to write post file") from exc

        # Perform the rename after write succeeds. Symlink failure is non-fatal:
        # the rename is the critical operation; a missing backward-compat symlink
        # only affects old bookmarked URLs, not application correctness.
        if needs_rename and old_dir is not None and new_dir is not None:
            try:
                shutil.move(str(old_dir), str(new_dir))
            except OSError as exc:
                logger.error("Failed to rename post directory %s -> %s: %s", old_dir, new_dir, exc)
                await session.rollback()
                raise HTTPException(
                    status_code=500, detail="Failed to rename post directory"
                ) from exc

            try:
                os.symlink(new_dir.name, str(old_dir))
            except OSError as exc:
                logger.warning(
                    "Failed to create backward-compat symlink %s -> %s: %s",
                    old_dir,
                    new_dir.name,
                    exc,
                )
                symlink_warning = "Post path changed but legacy symlink could not be created"
                response.headers["X-Path-Compatibility-Warning"] = symlink_warning
                endpoint_warnings.append(symlink_warning)

            existing.file_path = new_file_path
            post_data.file_path = new_file_path
            existing.rendered_excerpt = new_rendered_excerpt
            existing.rendered_html = new_rendered_html

        try:
            await session.commit()
        except (OperationalError, IntegrityError) as exc:
            logger.error("DB commit failed for post update %s: %s", file_path, exc)
            if needs_rename and new_dir is not None and old_dir is not None and new_dir.exists():
                try:
                    # Remove the backward-compat symlink at old_dir if it was created
                    if old_dir.is_symlink():
                        old_dir.unlink()
                    shutil.move(str(new_dir), str(old_dir))
                except OSError as mv_exc:
                    logger.error(
                        "Failed to rollback directory rename %s -> %s: %s",
                        new_dir,
                        old_dir,
                        mv_exc,
                    )
            raise
        await session.refresh(existing)
        set_git_warning(
            response,
            await git_service.try_commit(f"Update post: {existing.file_path}"),
        )

        return _build_post_detail(
            existing,
            labels=body.labels,
            rendered_html=existing.rendered_html or "",
            warnings=endpoint_warnings,
        )


@router.delete("/{file_path:path}", status_code=204)
async def delete_post_endpoint(
    file_path: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
    delete_assets: bool = Query(False),
) -> None:
    """Delete a post."""
    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="Post not found")

        # Read post content for FTS cleanup before deleting the file
        existing_post_data = content_manager.read_post(file_path)
        old_content = existing_post_data.content if existing_post_data else ""

        delete_draft_directory_assets = existing.is_draft and file_path.endswith("/index.md")

        try:
            content_manager.delete_post(
                file_path,
                delete_assets=delete_assets or delete_draft_directory_assets,
            )
        except OSError as exc:
            logger.error("Failed to delete post file %s: %s", file_path, exc)
            raise HTTPException(status_code=500, detail="Failed to delete post file") from exc

        await session.execute(delete(PostLabelCache).where(PostLabelCache.post_id == existing.id))
        await _delete_post_fts(
            session,
            post_id=existing.id,
            title=existing.title,
            content=old_content,
        )
        await session.delete(existing)
        await session.commit()
        set_git_warning(response, await git_service.try_commit(f"Delete post: {file_path}"))
