"""Admin panel business logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import SQLAlchemyError

from backend.exceptions import BuiltinPageError, InternalServerError
from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    write_site_config,
)
from backend.models.page import PageCache
from backend.services.cache_service import upsert_page_cache
from backend.services.page_service import BUILTIN_PAGE_IDS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.filesystem.content_manager import ContentManager

logger = logging.getLogger(__name__)


def get_site_settings(cm: ContentManager) -> SiteConfig:
    """Return current site settings."""
    return cm.site_config


def update_site_settings(
    cm: ContentManager,
    *,
    title: str,
    description: str,
    timezone: str,
) -> SiteConfig:
    """Update site settings in index.toml and reload config."""
    cfg = cm.site_config
    updated = SiteConfig(
        title=title,
        description=description,
        timezone=timezone,
        favicon=cfg.favicon,
        pages=cfg.pages,
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
    return cm.site_config


def get_admin_pages(cm: ContentManager) -> list[dict[str, Any]]:
    """Return all pages with metadata for admin panel."""
    result: list[dict[str, Any]] = []
    for page in cm.site_config.pages:
        content = None
        if page.file:
            try:
                page_path = cm._validate_path(page.file)
            except ValueError:
                page_path = None
            if page_path is not None and page_path.exists():
                try:
                    content = page_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.warning("Failed to read admin page content %s: %s", page.file, exc)
                    content = None
        result.append(
            {
                "id": page.id,
                "title": page.title,
                "file": page.file,
                "is_builtin": page.id in BUILTIN_PAGE_IDS,
                "content": content,
            }
        )
    return result


async def _refresh_page_cache(
    session_factory: async_sessionmaker[AsyncSession],
    cm: ContentManager,
    *,
    page_id: str,
    title: str,
) -> None:
    """Refresh the derived cache row for a file-backed page."""
    raw = cm.read_page(page_id)
    if raw is None:
        msg = f"Failed to read page {page_id} for cache refresh"
        raise InternalServerError(msg)

    async with session_factory() as session:
        cache_updated = await upsert_page_cache(session, page_id, title, raw)
        if not cache_updated:
            msg = f"Failed to render page {page_id} for cache refresh"
            raise InternalServerError(msg)
        await session.commit()


async def _update_page_cache_title(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    page_id: str,
    title: str,
) -> None:
    """Update the cached page title without re-rendering markdown."""
    async with session_factory() as session:
        row = await session.get(PageCache, page_id)
        if row is None:
            logger.warning("Page %s title updated but cache row is missing", page_id)
            return
        row.title = title
        await session.commit()


def _rollback_page_title(
    cm: ContentManager,
    *,
    cfg: SiteConfig,
    current_pages: list[PageConfig],
    page_id: str,
    original_title: str,
    failure_context: str,
) -> None:
    """Restore the original title in site config after a failed update."""
    rollback_pages = [
        PageConfig(
            id=p.id,
            title=original_title if p.id == page_id else p.title,
            file=p.file,
        )
        for p in current_pages
    ]
    rollback_cfg = cfg.with_pages(rollback_pages)
    try:
        write_site_config(cm.content_dir, rollback_cfg)
        cm.reload_config()
    except OSError as rollback_exc:
        logger.error(
            "Failed to rollback title change for page %s %s: %s",
            page_id,
            failure_context,
            rollback_exc,
        )


async def create_page(
    session_factory: async_sessionmaker[AsyncSession],
    cm: ContentManager,
    *,
    page_id: str,
    title: str,
    body: str | None = None,
) -> PageConfig:
    """Create a new page entry and .md file."""
    cfg = cm.site_config
    if page_id in BUILTIN_PAGE_IDS:
        msg = f"Page id '{page_id}' is reserved"
        raise ValueError(msg)

    if any(p.id == page_id for p in cfg.pages):
        msg = f"Page '{page_id}' already exists"
        raise ValueError(msg)

    file_name = f"{page_id}.md"
    md_path = cm.content_dir / file_name
    initial_content = body if body is not None else f"# {title}\n"
    md_path.write_text(initial_content, encoding="utf-8")

    new_page = PageConfig(id=page_id, title=title, file=file_name)
    updated = cfg.with_pages([*cfg.pages, new_page])
    try:
        write_site_config(cm.content_dir, updated)
    except OSError:
        # Clean up the orphan .md file if config write fails
        try:
            md_path.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            logger.warning("Failed to clean up orphan page file %s: %s", md_path, cleanup_exc)
        raise
    cm.reload_config()

    try:
        await _refresh_page_cache(session_factory, cm, page_id=page_id, title=title)
    except (SQLAlchemyError, RuntimeError, InternalServerError) as exc:
        logger.error("Failed to refresh page cache for page %s", page_id, exc_info=exc)
        try:
            write_site_config(cm.content_dir, cfg)
            cm.reload_config()
        except OSError as rollback_exc:
            logger.error(
                "Failed to rollback site config after cache refresh failure for page %s: %s",
                page_id,
                rollback_exc,
            )
        else:
            try:
                md_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.warning(
                    "Failed to clean up page file %s after cache refresh failure: %s",
                    md_path,
                    cleanup_exc,
                )
        raise InternalServerError("Failed to refresh page cache") from exc

    return new_page


async def update_page(
    session_factory: async_sessionmaker[AsyncSession],
    cm: ContentManager,
    page_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
) -> None:
    """Update a page's title and/or content."""
    cfg = cm.site_config
    page = next((p for p in cfg.pages if p.id == page_id), None)
    if page is None:
        msg = f"Page '{page_id}' not found"
        raise ValueError(msg)

    original_title = page.title

    page_path = None
    original_content = None
    if page.file is not None and content is not None:
        try:
            page_path = cm._validate_path(page.file)
        except ValueError as exc:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg) from exc
        try:
            original_content = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.error("Failed to read existing page %s before update: %s", page_id, exc)
            msg = f"Failed to read page {page_id} before update"
            raise InternalServerError(msg) from exc

    if title is not None:
        pages = [
            PageConfig(id=p.id, title=title if p.id == page_id else p.title, file=p.file)
            for p in cfg.pages
        ]
        updated = cfg.with_pages(pages)
        write_site_config(cm.content_dir, updated)
        cm.reload_config()

    if content is not None and page.file:
        if page_path is None:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg)
        try:
            page_path.write_text(content, encoding="utf-8")
        except OSError:
            if title is not None:
                _rollback_page_title(
                    cm,
                    cfg=cfg,
                    current_pages=cm.site_config.pages,
                    page_id=page_id,
                    original_title=original_title,
                    failure_context="after page write failure",
                )
            raise

    updated_page = next((p for p in cm.site_config.pages if p.id == page_id), None)
    if updated_page is not None and updated_page.file is not None:
        try:
            if content is not None:
                await _refresh_page_cache(
                    session_factory,
                    cm,
                    page_id=page_id,
                    title=updated_page.title,
                )
            elif title is not None:
                await _update_page_cache_title(
                    session_factory,
                    page_id=page_id,
                    title=updated_page.title,
                )
        except (SQLAlchemyError, RuntimeError, InternalServerError) as exc:
            logger.error("Failed to refresh page cache for page %s", page_id, exc_info=exc)
            if content is not None and page_path is not None and original_content is not None:
                try:
                    page_path.write_text(original_content, encoding="utf-8")
                except OSError as rollback_exc:
                    logger.error(
                        "Failed to rollback page content for page %s: %s",
                        page_id,
                        rollback_exc,
                    )
            if title is not None:
                _rollback_page_title(
                    cm,
                    cfg=cfg,
                    current_pages=cm.site_config.pages,
                    page_id=page_id,
                    original_title=original_title,
                    failure_context="after cache refresh failure",
                )
            raise InternalServerError("Failed to refresh page cache") from exc


async def delete_page(
    session_factory: async_sessionmaker[AsyncSession],
    cm: ContentManager,
    page_id: str,
    *,
    delete_file: bool,
) -> None:
    """Remove a page from config and optionally delete the .md file."""
    if page_id in BUILTIN_PAGE_IDS:
        msg = f"Cannot delete built-in page '{page_id}'"
        raise BuiltinPageError(msg)

    cfg = cm.site_config
    page = next((p for p in cfg.pages if p.id == page_id), None)
    if page is None:
        msg = f"Page '{page_id}' not found"
        raise ValueError(msg)

    # Resolve the file path before modifying config so validation errors
    # are raised before any state changes.
    resolved_file_path = None
    if delete_file and page.file:
        try:
            resolved_file_path = cm._validate_path(page.file)
        except ValueError as exc:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg) from exc

    # Update config first so it stays consistent even if file deletion fails.
    updated = cfg.with_pages([p for p in cfg.pages if p.id != page_id])
    write_site_config(cm.content_dir, updated)
    cm.reload_config()

    # Delete the file after config is updated. If deletion fails, the config
    # is already correct and a cache rebuild will clean up any references.
    if resolved_file_path is not None and resolved_file_path.exists():
        try:
            resolved_file_path.unlink()
        except OSError as exc:
            logger.warning(
                "Failed to delete page file %s (config already updated): %s",
                resolved_file_path,
                exc,
            )

    if delete_file or page.file is None:
        try:
            async with session_factory() as session:
                await session.execute(sa_delete(PageCache).where(PageCache.page_id == page_id))
                await session.commit()
        except (SQLAlchemyError, OSError):
            logger.warning(
                "Failed to remove cache for page %s; will clean on rebuild",
                page_id,
                exc_info=True,
            )


def update_page_order(cm: ContentManager, pages: list[PageConfig]) -> None:
    """Replace the page list with a new ordered list."""
    cfg = cm.site_config
    updated = cfg.with_pages(pages)
    write_site_config(cm.content_dir, updated)
    cm.reload_config()


def set_favicon(cm: ContentManager, *, extension: str, data: bytes) -> SiteConfig:
    """Save favicon bytes to content/assets/favicon{extension} and update index.toml."""
    if not re.fullmatch(r'\.[a-zA-Z0-9]+', extension):
        msg = f"Invalid favicon extension: {extension!r}"
        raise ValueError(msg)
    assets_dir = cm.content_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    old_favicon = cm.site_config.favicon
    if old_favicon is not None:
        old_path = cm.content_dir / old_favicon
        old_ext = Path(old_favicon).suffix
        if old_ext != extension:
            try:
                old_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove old favicon %s: %s", old_path, exc)

    favicon_rel = f"assets/favicon{extension}"
    favicon_path = cm.content_dir / favicon_rel
    favicon_path.write_bytes(data)

    cfg = cm.site_config
    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        favicon=favicon_rel,
        pages=cfg.pages,
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
    return cm.site_config


def remove_favicon(cm: ContentManager) -> SiteConfig:
    """Remove the favicon file and clear the favicon field from index.toml."""
    cfg = cm.site_config
    if cfg.favicon is not None:
        favicon_path = cm.content_dir / cfg.favicon
        try:
            favicon_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove favicon file %s: %s", favicon_path, exc)

    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        favicon=None,
        pages=cfg.pages,
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
    return cm.site_config
