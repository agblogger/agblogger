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
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_content_manager,
    get_current_user,
    get_git_service,
    get_session,
    require_admin,
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
    PostCreate,
    PostDetail,
    PostEditResponse,
    PostListResponse,
    PostUpdate,
    SearchResult,
)
from backend.services.datetime_service import format_iso, now_utc
from backend.services.git_service import GitService
from backend.services.label_service import ensure_label_cache_entry
from backend.services.post_service import get_post, list_posts, search_posts
from backend.services.slug_service import generate_post_path, generate_post_slug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"])

_FTS_DELETE_SQL = text(
    "INSERT INTO posts_fts(posts_fts, rowid, title, content) "
    "VALUES ('delete', :rowid, :title, :content)"
)

_FTS_INSERT_SQL = text(
    "INSERT INTO posts_fts(rowid, title, content) VALUES (:rowid, :title, :content)"
)


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


async def _render_post(content: str, file_path: str) -> tuple[str, str]:
    """Render excerpt and full HTML for a post in parallel, with URL rewriting."""
    md_excerpt = generate_markdown_excerpt(content)

    async def _render_excerpt() -> str:
        if not md_excerpt:
            return ""
        raw = await render_markdown_excerpt(md_excerpt)
        return rewrite_relative_urls(raw, file_path)

    async def _render_html() -> str:
        raw = await render_markdown(content)
        return rewrite_relative_urls(raw, file_path)

    rendered_excerpt, rendered_html = await asyncio.gather(
        _render_excerpt(),
        _render_html(),
    )
    return rendered_excerpt, rendered_html


def _build_post_detail(
    post: PostCache,
    *,
    labels: list[str],
    rendered_html: str,
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
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
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

    # Prefer index.md
    md_file = next(
        ((name, data) for name, data in md_files if name == "index.md"),
        md_files[0],
    )
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

    posts_dir = content_manager.content_dir / "posts"
    post_path = generate_post_path(post_data.title, posts_dir)
    file_path = str(post_path.relative_to(content_manager.content_dir))
    post_data.file_path = file_path

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

    # Catch pandoc rendering failures and clean up assets
    try:
        rendered_excerpt, rendered_html = await _render_post(post_data.content, file_path)
    except RuntimeError as exc:
        logger.error("Pandoc rendering failed during upload of %s: %s", file_path, exc)
        for asset in written_assets:
            asset.unlink(missing_ok=True)
        if post_dir.exists() and not any(post_dir.iterdir()):
            post_dir.rmdir()
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc

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
    await git_service.try_commit(f"Upload post: {file_path}")

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
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
) -> dict[str, list[str]]:
    """Upload asset files to a post's directory."""
    # Verify post exists
    stmt = select(PostCache).where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    post_dir = (content_manager.content_dir / file_path).parent
    uploaded: list[str] = []
    total_size = 0

    for upload_file in files:
        content = await upload_file.read()
        if len(content) > _MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail=f"File too large: {upload_file.filename}")
        total_size += len(content)
        if total_size > _MAX_TOTAL_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="Total upload size exceeds 50 MB limit")
        filename = FilePath(upload_file.filename or "upload").name
        if not filename or filename.startswith("."):
            raise HTTPException(status_code=400, detail=f"Invalid filename: {upload_file.filename}")
        dest = post_dir / filename
        # Handle filesystem errors during asset write
        try:
            dest.write_bytes(content)
        except OSError as exc:
            logger.error("Failed to write asset %s: %s", dest, exc)
            raise HTTPException(
                status_code=500, detail=f"Failed to write asset: {filename}"
            ) from exc
        uploaded.append(filename)

    if uploaded:
        await git_service.try_commit(f"Upload assets to {file_path}: {', '.join(uploaded)}")

    return {"uploaded": uploaded}


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
        # Check ownership via a lightweight query on the cache row
        stmt = select(PostCache.author_username).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        author_username = result.scalar_one_or_none()
        if author_username != user.username:
            raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("", response_model=PostDetail, status_code=201)
async def create_post_endpoint(
    body: PostCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_admin)],
) -> PostDetail:
    """Create a new post."""
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

    # Catch pandoc rendering failures
    try:
        rendered_excerpt, rendered_html = await _render_post(post_data.content, file_path)
    except RuntimeError as exc:
        logger.error("Pandoc rendering failed for new post %s: %s", file_path, exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc

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
    await git_service.try_commit(f"Create post: {file_path}")

    return _build_post_detail(post, labels=body.labels, rendered_html=rendered_html)


@router.put("/{file_path:path}", response_model=PostDetail)
async def update_post_endpoint(
    file_path: str,
    body: PostUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_admin)],
) -> PostDetail:
    """Update an existing post."""
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
    md_excerpt = generate_markdown_excerpt(post_data.content)

    # Render excerpt and full HTML in parallel; catch pandoc failures
    try:
        raw_rendered_excerpt, raw_rendered_html = await asyncio.gather(
            render_markdown_excerpt(md_excerpt) if md_excerpt else asyncio.sleep(0, result=""),
            render_markdown(post_data.content),
        )
    except RuntimeError as exc:
        logger.error("Pandoc rendering failed for post %s: %s", file_path, exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc
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

                new_file_path = str((new_dir / "index.md").relative_to(content_manager.content_dir))

                # Rewrite URLs with new path (reuse already-rendered HTML)
                new_rendered_excerpt = rewrite_relative_urls(raw_rendered_excerpt, new_file_path)
                new_rendered_html = rewrite_relative_urls(raw_rendered_html, new_file_path)

                needs_rename = True

    previous_title = existing.title
    previous_content = existing_post_data.content if existing_post_data else ""

    existing.title = title
    existing.author = author
    existing.author_username = author_username
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

    # Perform the rename after write succeeds.
    # Known limitation: this rename + symlink sequence is not atomic.  If
    # shutil.move succeeds but os.symlink fails *and* the rollback move also
    # fails, the directory will exist at new_dir with no symlink at old_dir,
    # while the DB still references the old path.  A subsequent cache rebuild
    # from disk will reconcile the state, but until then the post may appear
    # missing.  Both failure paths are logged for manual recovery.
    if needs_rename and old_dir is not None and new_dir is not None:
        # Handle OSError during shutil.move
        try:
            shutil.move(str(old_dir), str(new_dir))
        except OSError as exc:
            logger.error("Failed to rename post directory %s -> %s: %s", old_dir, new_dir, exc)
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to rename post directory") from exc

        # Handle OSError during os.symlink; rollback move on failure
        try:
            os.symlink(new_dir.name, str(old_dir))
        except OSError as exc:
            logger.error("Failed to create symlink %s -> %s: %s", old_dir, new_dir.name, exc)
            # Rollback: move directory back to original location
            try:
                shutil.move(str(new_dir), str(old_dir))
            except OSError as rollback_exc:
                logger.error(
                    "Failed to rollback directory rename %s -> %s: %s",
                    new_dir,
                    old_dir,
                    rollback_exc,
                )
            await session.rollback()
            raise HTTPException(
                status_code=500, detail="Failed to create backward-compat symlink"
            ) from exc

        existing.file_path = new_file_path
        post_data.file_path = new_file_path
        existing.rendered_excerpt = new_rendered_excerpt
        existing.rendered_html = new_rendered_html

    await session.commit()
    await session.refresh(existing)
    await git_service.try_commit(f"Update post: {existing.file_path}")

    return _build_post_detail(
        existing,
        labels=body.labels,
        rendered_html=existing.rendered_html or "",
    )


@router.delete("/{file_path:path}", status_code=204)
async def delete_post_endpoint(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
    delete_assets: bool = Query(False),
) -> None:
    """Delete a post."""
    stmt = select(PostCache).where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Post not found")

    # Read post content for FTS cleanup before deleting the file
    existing_post_data = content_manager.read_post(file_path)
    old_content = existing_post_data.content if existing_post_data else ""

    try:
        content_manager.delete_post(file_path, delete_assets=delete_assets)
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
    await git_service.try_commit(f"Delete post: {file_path}")
