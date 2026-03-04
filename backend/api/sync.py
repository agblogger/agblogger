"""Sync API endpoints for bidirectional content synchronization."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_content_manager, get_git_service, get_session, require_admin
from backend.filesystem.content_manager import ContentManager
from backend.models.user import User
from backend.services.git_service import GitService
from backend.services.sync_service import (
    FileEntry,
    compute_sync_plan,
    get_server_manifest,
    merge_post_file,
    normalize_post_frontmatter,
    scan_content_files,
    update_server_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

# Serialize sync commits to prevent concurrent modifications to the content
# directory and server manifest.
_sync_lock = asyncio.Lock()

_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _resolve_safe_path(content_dir: Path, file_path: str) -> Path:
    """Resolve a file path within content_dir, raising 400 on traversal attempts."""
    target = file_path.lstrip("/")
    full_path = (content_dir / target).resolve()
    if not full_path.is_relative_to(content_dir.resolve()):
        raise HTTPException(status_code=400, detail=f"Invalid file path: {file_path}")
    return full_path


# ── Schemas ──────────────────────────────────────────


class ManifestEntry(BaseModel):
    """Single file entry in a sync manifest."""

    file_path: str
    content_hash: str
    file_size: int
    file_mtime: str


class SyncStatusRequest(BaseModel):
    """Request to compute sync status with the client manifest."""

    client_manifest: list[ManifestEntry]


class SyncPlanItem(BaseModel):
    """Single item in a sync plan. Currently used for conflict items in the status response."""

    file_path: str
    action: str
    change_type: str = ""


class SyncStatusResponse(BaseModel):
    """Response containing the computed sync plan."""

    to_upload: list[str]
    to_download: list[str]
    to_delete_local: list[str]
    to_delete_remote: list[str]
    conflicts: list[SyncPlanItem]
    server_commit: str | None = None


class SyncConflictInfo(BaseModel):
    """Information about a conflict encountered during sync commit."""

    file_path: str
    body_conflicted: bool
    field_conflicts: list[str]


class SyncCommitResponse(BaseModel):
    """Response after finalizing a sync commit."""

    status: str
    files_synced: int
    warnings: list[str] = Field(default_factory=list)
    commit_hash: str | None = None
    conflicts: list[SyncConflictInfo] = Field(default_factory=list)
    to_download: list[str] = Field(default_factory=list)


# ── Endpoints ────────────────────────────────────────


@router.post("/status", response_model=SyncStatusResponse)
async def sync_status(
    body: SyncStatusRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_admin)],
) -> SyncStatusResponse:
    """Exchange manifests and compute sync plan."""
    client_manifest: dict[str, FileEntry] = {}
    for entry in body.client_manifest:
        client_manifest[entry.file_path] = FileEntry(
            file_path=entry.file_path,
            content_hash=entry.content_hash,
            file_size=entry.file_size,
            file_mtime=entry.file_mtime,
        )

    server_manifest = await get_server_manifest(session)
    server_current = scan_content_files(content_manager.content_dir)
    plan = compute_sync_plan(client_manifest, server_manifest, server_current)

    conflicts = [
        SyncPlanItem(
            file_path=c.file_path,
            action=c.action,
            change_type=c.change_type,
        )
        for c in plan.conflicts
    ]

    return SyncStatusResponse(
        to_upload=plan.to_upload,
        to_download=plan.to_download,
        to_delete_local=plan.to_delete_local,
        to_delete_remote=plan.to_delete_remote,
        conflicts=conflicts,
        server_commit=await git_service.head_commit(),
    )


@router.get("/download/{file_path:path}")
async def sync_download(
    file_path: str,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    user: Annotated[User, Depends(require_admin)],
) -> FileResponse:
    """Download a file from server to client."""
    full_path = _resolve_safe_path(content_manager.content_dir, file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)


@router.post("/commit", response_model=SyncCommitResponse)
async def sync_commit(
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_admin)],
    metadata: Annotated[str, Form()] = "{}",
    files: list[UploadFile] | None = File(default=None),
) -> SyncCommitResponse:
    """Finalize sync: upload files, merge conflicts, normalize, update manifest and caches.

    Accepts multipart form data with:
    - ``metadata``: JSON string containing ``deleted_files`` and ``last_sync_commit``
    - ``files``: uploaded files whose filenames encode the relative path
    """
    async with _sync_lock:
        return await _sync_commit_inner(
            metadata_json=metadata,
            upload_files=files or [],
            session=session,
            content_manager=content_manager,
            git_service=git_service,
            user=user,
        )


async def _sync_commit_inner(
    *,
    metadata_json: str,
    upload_files: list[UploadFile],
    session: AsyncSession,
    content_manager: ContentManager,
    git_service: GitService,
    user: User,
) -> SyncCommitResponse:
    """Inner sync commit logic, called under _sync_lock."""
    content_dir = content_manager.content_dir

    # ── Parse metadata ──
    try:
        meta = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid metadata JSON in sync commit: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from exc

    raw_deleted = meta.get("deleted_files", [])
    if not isinstance(raw_deleted, list) or not all(isinstance(f, str) for f in raw_deleted):
        raise HTTPException(status_code=400, detail="deleted_files must be a list of strings")
    deleted_files: list[str] = raw_deleted

    raw_commit = meta.get("last_sync_commit")
    if raw_commit is not None and not isinstance(raw_commit, str):
        raise HTTPException(status_code=400, detail="last_sync_commit must be a string or null")
    last_sync_commit: str | None = raw_commit

    # Load old manifest before any changes (needed for new-vs-edit detection)
    old_manifest = await get_server_manifest(session)

    # ── Apply deletions ──
    for file_path in deleted_files:
        full_path = _resolve_safe_path(content_dir, file_path)
        if full_path.exists() and full_path.is_file():
            full_path.unlink()
            logger.info("Sync: deleted file %s", file_path.lstrip("/"))

    # ── Process uploaded files ──
    conflicts: list[SyncConflictInfo] = []
    to_download: list[str] = []
    uploaded_paths: list[str] = []
    sync_warnings: list[str] = []

    for upload in upload_files:
        if upload.filename is None:
            logger.warning("Sync upload with no filename, skipping")
            sync_warnings.append("Skipped file upload with no filename")
            continue

        target_path = upload.filename.lstrip("/")
        full_path = _resolve_safe_path(content_dir, target_path)

        # Read upload content (enforce size limit)
        upload_content = await upload.read(_MAX_UPLOAD_SIZE + 1)
        if len(upload_content) > _MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413, detail=f"File too large (max 10 MB): {target_path}"
            )

        # Read server's current content BEFORE writing upload
        server_content: str | None = None
        if full_path.exists() and full_path.is_file():
            try:
                server_content = full_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # Binary file on server — skip text-based merge
                server_content = None

        client_text: str
        try:
            client_text = upload_content.decode("utf-8")
        except UnicodeDecodeError:
            # Binary file — just write it, no merge
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_bytes(upload_content)
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"File I/O error writing {target_path}"
                ) from exc
            uploaded_paths.append(target_path)
            continue

        # Merge conflict detection: attempt smart merge only for markdown posts
        # under posts/ where the server has a different version.
        is_post_md = target_path.startswith("posts/") and target_path.endswith(".md")

        if server_content is not None and server_content != client_text and is_post_md:
            # Get base version from git for three-way merge
            base_content = await _get_base_content(git_service, last_sync_commit, target_path)
            try:
                merge_result = await merge_post_file(
                    base_content, server_content, client_text, git_service
                )
            except (subprocess.CalledProcessError, OSError) as exc:
                logger.error("Merge failed for %s: %s", target_path, exc)
                conflicts.append(
                    SyncConflictInfo(
                        file_path=target_path, body_conflicted=True, field_conflicts=[]
                    )
                )
                continue

            if merge_result.body_conflicted or merge_result.field_conflicts:
                # Conflict detected. Write merged content (which preserves non-conflicting
                # changes from both sides, e.g. label additions) but report the conflict
                # so the client knows which fields/body had server-wins resolution.
                conflicts.append(
                    SyncConflictInfo(
                        file_path=target_path,
                        body_conflicted=merge_result.body_conflicted,
                        field_conflicts=merge_result.field_conflicts,
                    )
                )
                try:
                    full_path.write_text(merge_result.merged_content, encoding="utf-8")
                except OSError as exc:
                    raise HTTPException(
                        status_code=500, detail=f"File I/O error writing {target_path}"
                    ) from exc
                to_download.append(target_path)
            else:
                # Clean merge — write merged result
                try:
                    full_path.write_text(merge_result.merged_content, encoding="utf-8")
                except OSError as exc:
                    raise HTTPException(
                        status_code=500, detail=f"File I/O error writing {target_path}"
                    ) from exc
                to_download.append(target_path)

            uploaded_paths.append(target_path)
        else:
            # Non-conflict or non-post file: write client's version
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(client_text, encoding="utf-8")
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"File I/O error writing {target_path}"
                ) from exc
            uploaded_paths.append(target_path)

    # ── Normalize front matter for uploaded + merged post files ──
    fm_warnings = normalize_post_frontmatter(
        uploaded_files=uploaded_paths,
        old_manifest=old_manifest,
        content_dir=content_dir,
        default_author=content_manager.site_config.default_author,
        default_author_username=user.username,
    )

    # ── Git commit ──
    git_failed = False
    username = user.display_name or user.username
    try:
        await git_service.commit_all(f"Sync commit by {username}")
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Git commit failed during sync by %s (exit %d): %s",
            username,
            exc.returncode,
            exc.stderr.strip() if exc.stderr else "no stderr",
        )
        sync_warnings.append(
            "Git commit failed; sync history may be degraded. "
            "Three-way merge on the next sync may produce incorrect results."
        )
        git_failed = True

    # ── Update manifest and rebuild caches ──
    # Wrap manifest update and cache rebuild in try/except so sync still
    # returns even if post-commit operations fail (files are already committed to git).
    try:
        current_files = scan_content_files(content_dir)
        await update_server_manifest(session, current_files)
    except (OSError, OperationalError, RuntimeError) as exc:
        logger.error("Manifest update failed during sync commit: %s", exc)
        sync_warnings.append("Server manifest update failed; next sync may show stale data.")

    try:
        content_manager.reload_config()
    except Exception as exc:
        logger.warning("Config reload failed during sync: %s", exc)
        sync_warnings.append("Config reload failed; site settings may be stale until restart.")

    cache_warnings: list[str] = []
    try:
        from backend.services.cache_service import rebuild_cache

        _post_count, cache_warnings = await rebuild_cache(session, content_manager)
    except (OSError, OperationalError, RuntimeError) as exc:
        logger.error("Cache rebuild failed during sync commit: %s", exc)
        sync_warnings.append(
            "Cache rebuild failed after sync; search and listing data may be stale "
            "until the next server restart."
        )

    files_changed = len(uploaded_paths) + len(deleted_files)
    all_warnings = sync_warnings + fm_warnings + cache_warnings

    return SyncCommitResponse(
        status="error" if git_failed else "ok",
        files_synced=files_changed,
        warnings=all_warnings,
        commit_hash=None if git_failed else await git_service.head_commit(),
        conflicts=conflicts,
        to_download=to_download,
    )


async def _get_base_content(
    git_service: GitService,
    last_sync_commit: str | None,
    file_path: str,
) -> str | None:
    """Retrieve the base version of a file from git history.

    Returns None if no valid commit is available or the file didn't exist at that commit.
    """
    if last_sync_commit is None:
        return None
    if not await git_service.commit_exists(last_sync_commit):
        logger.warning(
            "Sync base commit %s not found in repo; falling back to no base for %s",
            last_sync_commit,
            file_path,
        )
        return None
    try:
        return await git_service.show_file_at_commit(last_sync_commit, file_path)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Git error retrieving base for %s at %s (exit %d): %s",
            file_path,
            last_sync_commit,
            exc.returncode,
            exc.stderr.strip() if exc.stderr else "no stderr",
        )
        return None
