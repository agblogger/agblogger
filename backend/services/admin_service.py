"""Admin panel business logic."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.exceptions import BuiltinPageError
from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    write_site_config,
)
from backend.models.post import PostCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.filesystem.content_manager import ContentManager
    from backend.filesystem.frontmatter import PostData
    from backend.models.user import User

BUILTIN_PAGE_IDS = {"timeline", "labels"}
_DISPLAY_NAME_DB_ERRORS = (OperationalError, IntegrityError)
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


def sync_site_default_author(cm: ContentManager, *, default_author: str) -> SiteConfig:
    """Persist the system-managed default author when it changes."""
    cfg = cm.site_config
    if cfg.default_author == default_author:
        return cfg
    updated = SiteConfig(
        title=cfg.title,
        description=cfg.description,
        default_author=default_author,
        timezone=cfg.timezone,
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

    updated = cfg.with_pages([p for p in cfg.pages if p.id != page_id])
    write_site_config(cm.content_dir, updated)
    cm.reload_config()


def update_page_order(cm: ContentManager, pages: list[PageConfig]) -> None:
    """Replace the page list with a new ordered list."""
    cfg = cm.site_config
    updated = cfg.with_pages(pages)
    write_site_config(cm.content_dir, updated)
    cm.reload_config()


async def update_user_display_name(
    session: AsyncSession,
    cm: ContentManager,
    *,
    user: User,
    display_name: str | None,
) -> str | None:
    """Update a user's display name and retroactively update all their posts.

    Updates the author field in both the database cache and on-disk markdown files
    for all posts where author_username matches the user's username.
    """
    from backend.services.datetime_service import format_iso, now_utc

    author_value = display_name or user.username
    stmt = select(PostCache.file_path).where(PostCache.author_username == user.username)
    result = await session.execute(stmt)
    file_paths = [row[0] for row in result.all()]
    original_default_author = cm.site_config.default_author

    original_posts: dict[str, PostData] = {}
    updated_posts: dict[str, PostData] = {}
    for file_path in file_paths:
        post_data = cm.read_post(file_path)
        if post_data is None:
            msg = f"Failed to load post for display-name migration: {file_path}"
            logger.error(msg)
            raise OSError(msg)
        original_posts[file_path] = post_data
        updated_posts[file_path] = replace(post_data, author=author_value)

    def rollback_filesystem_changes(written_paths: list[str]) -> None:
        for written_path in reversed(written_paths):
            original_post = original_posts.get(written_path)
            if original_post is None:
                continue
            try:
                cm.write_post(written_path, original_post)
            except OSError as rollback_exc:
                logger.error(
                    "Failed to rollback display-name migration for post %s: %s",
                    written_path,
                    rollback_exc,
                )
        if cm.site_config.default_author != original_default_author:
            try:
                sync_site_default_author(cm, default_author=original_default_author)
            except OSError as rollback_exc:
                logger.error(
                    "Failed to rollback default author after display-name migration: %s",
                    rollback_exc,
                )

    written_paths: list[str] = []
    current_path: str | None = None
    try:
        for current_path, post_data in updated_posts.items():
            cm.write_post(current_path, post_data)
            written_paths.append(current_path)
        current_path = None
        sync_site_default_author(cm, default_author=author_value)
    except OSError as exc:
        failed_path = current_path if current_path not in written_paths else None
        rollback_filesystem_changes(written_paths)
        if failed_path is not None:
            msg = f"Failed to update author in {failed_path}: {exc}"
        else:
            msg = f"Failed to update site config: {exc}"
        raise OSError(msg) from exc

    original_display_name = user.display_name
    original_updated_at = user.updated_at
    user.display_name = display_name
    user.updated_at = format_iso(now_utc())
    session.add(user)

    try:
        await session.execute(
            update(PostCache)
            .where(PostCache.author_username == user.username)
            .values(author=author_value)
        )
        await session.commit()
    except _DISPLAY_NAME_DB_ERRORS as exc:
        logger.error("Database error during display name update: %s", exc)
        await session.rollback()
        user.display_name = original_display_name
        user.updated_at = original_updated_at
        rollback_filesystem_changes(written_paths)
        raise
    return display_name


async def sync_default_author_from_admin(
    session: AsyncSession,
    cm: ContentManager,
    *,
    admin_username: str,
) -> SiteConfig:
    """Ensure the system-managed default author matches the sole editing admin."""
    from backend.models.user import User

    result = await session.execute(
        select(User.username, User.display_name).where(User.is_admin.is_(True)).order_by(User.id)
    )
    admins = result.all()
    if len(admins) != 1:
        return cm.site_config
    username, display_name = admins[0]
    if username != admin_username:
        return cm.site_config
    return sync_site_default_author(cm, default_author=display_name or username)
