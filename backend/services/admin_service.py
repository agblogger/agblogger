"""Admin panel business logic."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete as sa_delete

from backend.exceptions import BuiltinPageError
from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    write_site_config,
)
from backend.models.page import PageCache
from backend.services.cache_service import upsert_page_cache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.filesystem.content_manager import ContentManager

BUILTIN_PAGE_IDS = {"timeline", "labels"}
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


async def create_page(
    session_factory: async_sessionmaker[AsyncSession],
    cm: ContentManager,
    *,
    page_id: str,
    title: str,
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
    md_path.write_text(f"# {title}\n", encoding="utf-8")

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

    raw = cm.read_page(page_id)
    if raw is not None:
        try:
            async with session_factory() as session:
                await upsert_page_cache(session, page_id, title, raw)
                await session.commit()
        except Exception:
            logger.warning(
                "Failed to cache page %s; will populate on rebuild", page_id, exc_info=True
            )

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

    if title is not None:
        pages = [
            PageConfig(id=p.id, title=title if p.id == page_id else p.title, file=p.file)
            for p in cfg.pages
        ]
        updated = cfg.with_pages(pages)
        write_site_config(cm.content_dir, updated)
        cm.reload_config()

    if content is not None and page.file:
        try:
            page_path = cm._validate_path(page.file)
        except ValueError as exc:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg) from exc
        try:
            page_path.write_text(content, encoding="utf-8")
        except OSError:
            if title is not None:
                # Roll back the title change in config
                rollback_pages = [
                    PageConfig(
                        id=p.id,
                        title=original_title if p.id == page_id else p.title,
                        file=p.file,
                    )
                    for p in cm.site_config.pages
                ]
                rollback_cfg = cfg.with_pages(rollback_pages)
                try:
                    write_site_config(cm.content_dir, rollback_cfg)
                    cm.reload_config()
                except OSError as rollback_exc:
                    logger.error(
                        "Failed to rollback title change for page %s: %s",
                        page_id,
                        rollback_exc,
                    )
            raise

    updated_page = next((p for p in cm.site_config.pages if p.id == page_id), None)
    if updated_page is not None and updated_page.file is not None:
        raw = cm.read_page(page_id)
        if raw is not None:
            try:
                async with session_factory() as session:
                    await upsert_page_cache(session, page_id, updated_page.title, raw)
                    await session.commit()
            except Exception:
                logger.warning(
                    "Failed to cache page %s; will populate on rebuild", page_id, exc_info=True
                )


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

    try:
        async with session_factory() as session:
            await session.execute(sa_delete(PageCache).where(PageCache.page_id == page_id))
            await session.commit()
    except Exception:
        logger.warning(
            "Failed to remove cache for page %s; will clean on rebuild", page_id, exc_info=True
        )


def update_page_order(cm: ContentManager, pages: list[PageConfig]) -> None:
    """Replace the page list with a new ordered list."""
    cfg = cm.site_config
    updated = cfg.with_pages(pages)
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
