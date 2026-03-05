"""Admin panel business logic."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.exceptions import BuiltinPageError
from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    write_site_config,
)

if TYPE_CHECKING:
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
    default_author: str,
    timezone: str,
) -> SiteConfig:
    """Update site settings in index.toml and reload config."""
    cfg = cm.site_config
    updated = SiteConfig(
        title=title,
        description=description,
        default_author=default_author,
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


def create_page(cm: ContentManager, *, page_id: str, title: str) -> PageConfig:
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
    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        default_author=cfg.default_author,
        timezone=cfg.timezone,
        pages=[*cfg.pages, new_page],
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
    return new_page


def update_page(
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

    if title is not None:
        pages = [
            PageConfig(id=p.id, title=title if p.id == page_id else p.title, file=p.file)
            for p in cfg.pages
        ]
        updated = SiteConfig(
            title=cfg.title,
            description=cfg.description,
            default_author=cfg.default_author,
            timezone=cfg.timezone,
            pages=pages,
        )
        write_site_config(cm.content_dir, updated)
        cm.reload_config()

    if content is not None and page.file:
        try:
            page_path = cm._validate_path(page.file)
        except ValueError as exc:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg) from exc
        page_path.write_text(content, encoding="utf-8")


def delete_page(cm: ContentManager, page_id: str, *, delete_file: bool) -> None:
    """Remove a page from config and optionally delete the .md file."""
    if page_id in BUILTIN_PAGE_IDS:
        msg = f"Cannot delete built-in page '{page_id}'"
        raise BuiltinPageError(msg)

    cfg = cm.site_config
    page = next((p for p in cfg.pages if p.id == page_id), None)
    if page is None:
        msg = f"Page '{page_id}' not found"
        raise ValueError(msg)

    if delete_file and page.file:
        try:
            file_path = cm._validate_path(page.file)
        except ValueError as exc:
            msg = f"Page '{page_id}' has an invalid file path"
            raise ValueError(msg) from exc
        if file_path.exists():
            file_path.unlink()

    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        default_author=cfg.default_author,
        timezone=cfg.timezone,
        pages=[p for p in cfg.pages if p.id != page_id],
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()


def update_page_order(cm: ContentManager, pages: list[PageConfig]) -> None:
    """Replace the page list with a new ordered list."""
    cfg = cm.site_config
    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        default_author=cfg.default_author,
        timezone=cfg.timezone,
        pages=pages,
    )
    write_site_config(cm.content_dir, updated)
    cm.reload_config()
