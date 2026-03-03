"""Admin panel API endpoints."""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_content_manager,
    get_git_service,
    get_session,
    require_admin,
)
from backend.exceptions import BuiltinPageError
from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import PageConfig
from backend.models.user import User
from backend.schemas.admin import (
    AdminPageConfig,
    AdminPagesResponse,
    PageCreate,
    PageOrderUpdate,
    PageUpdate,
    PasswordChange,
    SiteSettingsResponse,
    SiteSettingsUpdate,
)
from backend.services.admin_service import (
    create_page,
    delete_page,
    get_admin_pages,
    get_site_settings,
    update_page,
    update_page_order,
    update_site_settings,
)
from backend.services.auth_service import hash_password, revoke_user_credentials, verify_password
from backend.services.datetime_service import format_iso, now_utc
from backend.services.git_service import GitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_PAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PAGE_ID_ERROR = (
    "Invalid page ID: must start with a lowercase letter or digit, "
    "and contain only lowercase alphanumeric characters, hyphens, or underscores."
)


@router.get("/site", response_model=SiteSettingsResponse)
async def get_settings(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[User, Depends(require_admin)],
) -> SiteSettingsResponse:
    """Get current site settings."""
    cfg = get_site_settings(content_manager)
    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        default_author=cfg.default_author,
        timezone=cfg.timezone,
    )


@router.put("/site", response_model=SiteSettingsResponse)
async def update_settings(
    body: SiteSettingsUpdate,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
) -> SiteSettingsResponse:
    """Update site settings."""
    try:
        cfg = update_site_settings(
            content_manager,
            title=body.title,
            description=body.description,
            default_author=body.default_author,
            timezone=body.timezone,
        )
    except OSError as exc:
        logger.error("Failed to update site settings: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to write site settings") from exc
    await git_service.try_commit("Update site settings")
    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        default_author=cfg.default_author,
        timezone=cfg.timezone,
    )


@router.get("/pages", response_model=AdminPagesResponse)
async def list_pages(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[User, Depends(require_admin)],
) -> AdminPagesResponse:
    """Get all pages with content for admin panel."""
    pages = get_admin_pages(content_manager)
    return AdminPagesResponse(pages=[AdminPageConfig(**p) for p in pages])


@router.post("/pages", response_model=AdminPageConfig, status_code=201)
async def create_page_endpoint(
    body: PageCreate,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
) -> AdminPageConfig:
    """Create a new page."""
    try:
        page = create_page(content_manager, page_id=body.id, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Failed to create page %s: %s", body.id, exc)
        raise HTTPException(status_code=500, detail="Failed to create page") from exc
    await git_service.try_commit(f"Create page: {body.id}")
    return AdminPageConfig(
        id=page.id,
        title=page.title,
        file=page.file,
        is_builtin=False,
        content=f"# {body.title}\n",
    )


@router.put("/pages/order", response_model=AdminPagesResponse)
async def update_order(
    body: PageOrderUpdate,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
) -> AdminPagesResponse:
    """Update page order."""
    pages = [PageConfig(id=p.id, title=p.title, file=p.file) for p in body.pages]
    try:
        update_page_order(content_manager, pages)
    except OSError as exc:
        logger.error("Failed to update page order: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update page order") from exc
    await git_service.try_commit("Update page order")
    admin_pages = get_admin_pages(content_manager)
    return AdminPagesResponse(pages=[AdminPageConfig(**p) for p in admin_pages])


@router.put("/pages/{page_id}")
async def update_page_endpoint(
    page_id: str,
    body: PageUpdate,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
) -> dict[str, str]:
    """Update a page's title and/or content."""
    if not _PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail=_PAGE_ID_ERROR)
    try:
        update_page(content_manager, page_id, title=body.title, content=body.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Failed to update page %s: %s", page_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update page") from exc
    await git_service.try_commit(f"Update page: {page_id}")
    return {"status": "ok"}


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page_endpoint(
    page_id: str,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    _user: Annotated[User, Depends(require_admin)],
    delete_file: bool = Query(default=True),
) -> None:
    """Delete a page."""
    if not _PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail=_PAGE_ID_ERROR)
    try:
        delete_page(content_manager, page_id, delete_file=delete_file)
    except BuiltinPageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Failed to delete page %s: %s", page_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete page") from exc
    await git_service.try_commit(f"Delete page: {page_id}")


@router.put("/password")
async def change_password(
    body: PasswordChange,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_admin)],
) -> dict[str, str]:
    """Change admin password."""
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.updated_at = format_iso(now_utc())
    await revoke_user_credentials(session, user.id)
    session.add(user)
    await session.commit()
    return {"status": "ok"}
