"""Admin panel API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import (
    AsyncWriteLock,
    get_content_manager,
    get_content_size_tracker,
    get_content_write_lock,
    get_git_service,
    get_session,
    get_session_factory,
    require_admin,
    set_git_warning,
)
from backend.api.deps import (
    get_settings as get_settings_dep,
)
from backend.config import Settings
from backend.exceptions import BuiltinPageError
from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import PageConfig, SiteConfig, serialize_site_config
from backend.models.user import AdminUser
from backend.schemas.admin import (
    PAGE_ID_ERROR,
    PAGE_ID_PATTERN,
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
    remove_favicon,
    set_favicon,
    update_page,
    update_page_order,
    update_site_settings,
)
from backend.services.auth_service import hash_password, revoke_admin_credentials, verify_password
from backend.services.git_service import GitService
from backend.services.rate_limit_service import InMemoryRateLimiter
from backend.services.storage_quota import ContentSizeTracker
from backend.services.upload_limits import MAX_FAVICON_SIZE
from backend.utils.datetime import format_iso, now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/site", response_model=SiteSettingsResponse)
async def get_settings(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SiteSettingsResponse:
    """Get current site settings."""
    cfg = get_site_settings(content_manager)
    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        password_change_disabled=settings.disable_password_change,
        favicon=cfg.favicon,
    )


@router.put("/site", response_model=SiteSettingsResponse)
async def update_settings(
    body: SiteSettingsUpdate,
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SiteSettingsResponse:
    """Update site settings."""
    async with content_write_lock:
        old_cfg = get_site_settings(content_manager)
        projected_cfg = SiteConfig(
            title=body.title,
            description=body.description,
            timezone=body.timezone,
            favicon=old_cfg.favicon,
            pages=old_cfg.pages,
        )
        index_path = content_manager.content_dir / "index.toml"
        old_index_size = content_size_tracker.file_size(index_path)
        projected_index_size = len(serialize_site_config(projected_cfg))
        projected_delta = projected_index_size - old_index_size
        content_size_tracker.require_quota(projected_delta)
        try:
            cfg = update_site_settings(
                content_manager,
                title=body.title,
                description=body.description,
                timezone=body.timezone,
            )
        except OSError as exc:
            logger.error("Failed to update site settings: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to write site settings") from exc
        content_size_tracker.adjust(content_size_tracker.file_size(index_path) - old_index_size)
        set_git_warning(response, await git_service.try_commit("Update site settings"))
        return SiteSettingsResponse(
            title=cfg.title,
            description=cfg.description,
            timezone=cfg.timezone,
            password_change_disabled=settings.disable_password_change,
            favicon=cfg.favicon,
        )


_ALLOWED_FAVICON_CONTENT_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/x-icon": ".ico",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


def _get_old_favicon_size(
    content_manager: ContentManager, content_size_tracker: ContentSizeTracker
) -> int:
    old_favicon = content_manager.site_config.favicon
    if old_favicon is None:
        return 0
    try:
        old_path = content_manager.validate_path(old_favicon)
        return content_size_tracker.file_size(old_path)
    except ValueError:
        logger.warning("Invalid old favicon path in quota check: %s", old_favicon)
        return 0


@router.post("/favicon", response_model=SiteSettingsResponse)
async def upload_favicon(
    file: Annotated[UploadFile, File()],
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SiteSettingsResponse:
    """Upload or replace the site favicon."""
    content_type = (file.content_type or "").split(";")[0].strip()
    extension = _ALLOWED_FAVICON_CONTENT_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {content_type}. Allowed: PNG, ICO, SVG, WebP.",
        )

    data = await file.read()
    if len(data) > MAX_FAVICON_SIZE:
        raise HTTPException(status_code=413, detail="Favicon file exceeds 2 MB limit.")

    async with content_write_lock:
        old_size = _get_old_favicon_size(content_manager, content_size_tracker)
        content_size_tracker.require_quota(len(data) - old_size)

        try:
            cfg = set_favicon(content_manager, extension=extension, data=data)
        except (ValueError, OSError) as exc:
            logger.error("Failed to save favicon: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to save favicon.") from exc

        new_path = content_manager.content_dir / f"assets/favicon{extension}"
        content_size_tracker.adjust(content_size_tracker.file_size(new_path) - old_size)
        set_git_warning(response, await git_service.try_commit("Update site favicon"))

    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        password_change_disabled=settings.disable_password_change,
        favicon=cfg.favicon,
    )


@router.delete("/favicon", response_model=SiteSettingsResponse)
async def delete_favicon(
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SiteSettingsResponse:
    """Remove the site favicon."""
    async with content_write_lock:
        old_size = _get_old_favicon_size(content_manager, content_size_tracker)

        try:
            cfg = remove_favicon(content_manager)
        except OSError as exc:
            logger.error("Failed to remove favicon: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to remove favicon.") from exc

        content_size_tracker.adjust(-old_size)
        set_git_warning(response, await git_service.try_commit("Remove site favicon"))

    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        password_change_disabled=settings.disable_password_change,
        favicon=cfg.favicon,
    )


@router.get("/pages", response_model=AdminPagesResponse)
async def list_pages(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> AdminPagesResponse:
    """Get all pages with content for admin panel."""
    pages = get_admin_pages(content_manager)
    return AdminPagesResponse(pages=[AdminPageConfig(**p) for p in pages])


@router.post("/pages", response_model=AdminPageConfig, status_code=201)
async def create_page_endpoint(
    body: PageCreate,
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> AdminPageConfig:
    """Create a new page."""
    initial_content = body.body if body.body is not None else f"# {body.title}\n"
    async with content_write_lock:
        cfg = content_manager.site_config
        page_path = content_manager.content_dir / f"{body.id}.md"
        index_path = content_manager.content_dir / "index.toml"
        old_page_size = content_size_tracker.file_size(page_path)
        old_index_size = content_size_tracker.file_size(index_path)
        projected_cfg = cfg.with_pages(
            [*cfg.pages, PageConfig(id=body.id, title=body.title, file=f"{body.id}.md")]
        )
        projected_delta = (
            len(initial_content.encode("utf-8"))
            - old_page_size
            + len(serialize_site_config(projected_cfg))
            - old_index_size
        )
        content_size_tracker.require_quota(projected_delta)
        try:
            page = await create_page(
                session_factory, content_manager, page_id=body.id, title=body.title, body=body.body
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            logger.error("Failed to create page %s: %s", body.id, exc)
            raise HTTPException(status_code=500, detail="Failed to create page") from exc
        content_size_tracker.adjust(
            (content_size_tracker.file_size(page_path) - old_page_size)
            + (content_size_tracker.file_size(index_path) - old_index_size)
        )
        set_git_warning(response, await git_service.try_commit(f"Create page: {body.id}"))
        return AdminPageConfig(
            id=page.id,
            title=page.title,
            file=page.file,
            is_builtin=False,
            content=initial_content,
        )


@router.put("/pages/order", response_model=AdminPagesResponse)
async def update_order(
    body: PageOrderUpdate,
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> AdminPagesResponse:
    """Update page order."""
    async with content_write_lock:
        pages = [PageConfig(id=p.id, title=p.title, file=p.file) for p in body.pages]
        cfg = content_manager.site_config
        index_path = content_manager.content_dir / "index.toml"
        old_index_size = content_size_tracker.file_size(index_path)
        projected_delta = len(serialize_site_config(cfg.with_pages(pages))) - old_index_size
        content_size_tracker.require_quota(projected_delta)
        try:
            update_page_order(content_manager, pages)
        except OSError as exc:
            logger.error("Failed to update page order: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to update page order") from exc
        content_size_tracker.adjust(content_size_tracker.file_size(index_path) - old_index_size)
        set_git_warning(response, await git_service.try_commit("Update page order"))
        admin_pages = get_admin_pages(content_manager)
        return AdminPagesResponse(pages=[AdminPageConfig(**p) for p in admin_pages])


@router.put("/pages/{page_id}")
async def update_page_endpoint(
    page_id: str,
    body: PageUpdate,
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, str]:
    """Update a page's title and/or content."""
    if not PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail=PAGE_ID_ERROR)
    async with content_write_lock:
        old_content_size = 0
        cfg = content_manager.site_config
        page_cfg = next((p for p in cfg.pages if p.id == page_id), None)
        page_path = None
        if page_cfg is not None and page_cfg.file is not None:
            try:
                page_path = content_manager.validate_path(page_cfg.file)
                old_content_size = content_size_tracker.file_size(page_path)
            except ValueError, OSError:
                logger.warning(
                    "Failed to resolve page path for size accounting: %s", page_id, exc_info=True
                )
                page_path = None
                old_content_size = 0
        index_path = content_manager.content_dir / "index.toml"
        old_index_size = content_size_tracker.file_size(index_path)
        if body.content is not None:
            new_size = len(body.content.encode("utf-8"))
        else:
            new_size = old_content_size
        if body.title is not None and page_cfg is not None:
            projected_cfg = cfg.with_pages(
                [
                    PageConfig(
                        id=p.id,
                        title=body.title if p.id == page_id else p.title,
                        file=p.file,
                    )
                    for p in cfg.pages
                ]
            )
            projected_index_size = len(serialize_site_config(projected_cfg))
        else:
            projected_index_size = old_index_size
        projected_delta = (new_size - old_content_size) + (projected_index_size - old_index_size)
        content_size_tracker.require_quota(projected_delta)
        try:
            await update_page(
                session_factory, content_manager, page_id, title=body.title, content=body.content
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            logger.error("Failed to update page %s: %s", page_id, exc)
            raise HTTPException(status_code=500, detail="Failed to update page") from exc
        final_content_size = (
            old_content_size if page_path is None else content_size_tracker.file_size(page_path)
        )
        content_size_tracker.adjust(
            (final_content_size - old_content_size)
            + (content_size_tracker.file_size(index_path) - old_index_size)
        )
        set_git_warning(response, await git_service.try_commit(f"Update page: {page_id}"))
        return {"status": "ok"}


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page_endpoint(
    page_id: str,
    response: Response,
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    delete_file: bool = Query(default=True),
) -> None:
    """Delete a page."""
    if not PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail=PAGE_ID_ERROR)
    async with content_write_lock:
        # Read page file size before deletion so the tracker can be adjusted.
        page_size = 0
        page_path = None
        index_path = content_manager.content_dir / "index.toml"
        old_index_size = content_size_tracker.file_size(index_path)
        if delete_file:
            cfg = content_manager.site_config
            page_cfg = next((p for p in cfg.pages if p.id == page_id), None)
            if page_cfg is not None and page_cfg.file is not None:
                try:
                    page_path = content_manager.validate_path(page_cfg.file)
                    page_size = content_size_tracker.file_size(page_path)
                except (ValueError, OSError) as exc:
                    logger.warning(
                        "Failed to read page size before deletion for %s: %s", page_id, exc
                    )
        try:
            await delete_page(session_factory, content_manager, page_id, delete_file=delete_file)
        except BuiltinPageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            logger.error("Failed to delete page %s: %s", page_id, exc)
            raise HTTPException(status_code=500, detail="Failed to delete page") from exc
        deleted_page_size = page_size if page_path is not None and not page_path.exists() else 0
        content_size_tracker.adjust(
            (content_size_tracker.file_size(index_path) - old_index_size) - deleted_page_size
        )
        set_git_warning(response, await git_service.try_commit(f"Delete page: {page_id}"))


_PASSWORD_CHANGE_MAX_FAILURES = 5
_PASSWORD_CHANGE_WINDOW_SECONDS = 300


@router.put("/password")
async def change_password(
    body: PasswordChange,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict[str, str | bool]:
    """Change admin password."""
    if settings.disable_password_change:
        raise HTTPException(
            status_code=403,
            detail="Password changes are disabled by server configuration",
        )
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    rate_key = f"password_change:{user.id}"
    limited, retry_after = limiter.is_limited(
        rate_key, _PASSWORD_CHANGE_MAX_FAILURES, _PASSWORD_CHANGE_WINDOW_SECONDS
    )
    if limited:
        raise HTTPException(
            status_code=429,
            detail="Too many failed password change attempts",
            headers={"Retry-After": str(retry_after)},
        )

    if not verify_password(body.current_password, user.password_hash):
        limiter.add_failure(rate_key, _PASSWORD_CHANGE_WINDOW_SECONDS)
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    limiter.clear(rate_key)
    user.password_hash = hash_password(body.new_password)
    user.updated_at = format_iso(now_utc())
    await revoke_admin_credentials(session, user.id)
    session.add(user)
    await session.commit()
    return {"status": "ok", "sessions_revoked": True}
