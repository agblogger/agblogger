"""Label API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_content_manager, get_git_service, get_session, require_auth
from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import LabelDef, write_labels_config
from backend.models.user import User
from backend.schemas.label import (
    LabelCreate,
    LabelDeleteResponse,
    LabelGraphResponse,
    LabelResponse,
    LabelUpdate,
)
from backend.schemas.post import PostListResponse
from backend.services.git_service import GitService
from backend.services.label_service import (
    create_label,
    delete_label,
    get_all_labels,
    get_label,
    get_label_graph,
    update_label,
)
from backend.services.post_service import get_posts_by_label

logger = logging.getLogger(__name__)


async def _persist_labels_and_commit(
    session: AsyncSession,
    content_manager: ContentManager,
    git_service: GitService,
    labels: dict[str, LabelDef],
    commit_message: str,
    error_context: str,
) -> None:
    """Write labels to TOML, commit DB changes, and create a git commit."""
    # Save current labels in case we need to restore on commit failure
    old_labels = dict(content_manager.labels)

    try:
        write_labels_config(content_manager.content_dir, labels)
        content_manager.reload_config()
    except OSError as exc:
        await session.rollback()
        logger.error("Failed to write labels.toml for %s", error_context, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to persist label to filesystem"
        ) from exc

    # Wrap session.commit with recovery -- restore TOML on failure
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        logger.error("DB commit failed for %s", error_context, exc_info=True)
        await session.rollback()
        # Restore old labels to TOML since DB commit failed
        try:
            write_labels_config(content_manager.content_dir, old_labels)
            content_manager.reload_config()
        except OSError:
            logger.error(
                "Failed to restore labels.toml after commit failure for %s",
                error_context,
                exc_info=True,
            )
        raise HTTPException(status_code=500, detail="Failed to commit label changes") from exc

    await git_service.try_commit(commit_message)


router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.get("", response_model=list[LabelResponse])
async def list_labels(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LabelResponse]:
    """List all labels."""
    return await get_all_labels(session)


@router.get("/graph", response_model=LabelGraphResponse)
async def label_graph(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LabelGraphResponse:
    """Get the full label DAG for graph visualization."""
    return await get_label_graph(session)


@router.post("", response_model=LabelResponse, status_code=201)
async def create_label_endpoint(
    body: LabelCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_auth)],
) -> LabelResponse:
    """Create a new label."""
    # Validate parents exist
    for parent_id in body.parents:
        parent = await get_label(session, parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail=f"Parent label '{parent_id}' not found")

    try:
        result = await create_label(session, body.id, body.names or None, body.parents or None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=409, detail="Label already exists")

    # Write to labels.toml first (filesystem is source of truth)
    labels = dict(content_manager.labels)
    labels[body.id] = LabelDef(
        id=body.id,
        names=body.names if body.names else [body.id],
        parents=body.parents,
    )
    await _persist_labels_and_commit(
        session,
        content_manager,
        git_service,
        labels,
        f"Create label: {body.id}",
        f"label {body.id}",
    )
    return result


@router.put("/{label_id}", response_model=LabelResponse)
async def update_label_endpoint(
    label_id: str,
    body: LabelUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_auth)],
) -> LabelResponse:
    """Update a label's names and parents."""
    existing = await get_label(session, label_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Label not found")

    # Validate parents exist
    for parent_id in body.parents:
        parent = await get_label(session, parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail=f"Parent label '{parent_id}' not found")

    try:
        result = await update_label(session, label_id, body.names, body.parents)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Label was deleted during update")

    # Persist to labels.toml first (filesystem is source of truth)
    labels = dict(content_manager.labels)
    labels[label_id] = LabelDef(
        id=label_id,
        names=body.names if body.names else [label_id],
        parents=body.parents,
    )
    await _persist_labels_and_commit(
        session,
        content_manager,
        git_service,
        labels,
        f"Update label: {label_id}",
        f"label {label_id}",
    )
    return result


@router.delete("/{label_id}", response_model=LabelDeleteResponse)
async def delete_label_endpoint(
    label_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    user: Annotated[User, Depends(require_auth)],
) -> LabelDeleteResponse:
    """Delete a label."""
    deleted = await delete_label(session, label_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Label not found")

    # Remove from labels.toml first (filesystem is source of truth)
    labels = dict(content_manager.labels)
    labels.pop(label_id, None)
    for key, label_def in labels.items():
        if label_id in label_def.parents:
            labels[key] = LabelDef(
                id=label_def.id,
                names=label_def.names,
                parents=[p for p in label_def.parents if p != label_id],
            )
    await _persist_labels_and_commit(
        session,
        content_manager,
        git_service,
        labels,
        f"Delete label: {label_id}",
        f"deleting {label_id}",
    )
    return LabelDeleteResponse(id=label_id)


@router.get("/{label_id}", response_model=LabelResponse)
async def get_label_endpoint(
    label_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LabelResponse:
    """Get a single label by ID."""
    label = await get_label(session, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")
    return label


@router.get("/{label_id}/posts", response_model=PostListResponse)
async def label_posts(
    label_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> PostListResponse:
    """Get posts for a specific label (including descendants)."""
    return await get_posts_by_label(session, label_id, page=page, per_page=per_page)
