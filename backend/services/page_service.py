"""Page service: top-level page retrieval from cache."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.page import PageCache
from backend.schemas.page import PageConfig, PageResponse, SiteConfigResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.filesystem.content_manager import ContentManager


logger = logging.getLogger(__name__)


def get_site_config(content_manager: ContentManager) -> SiteConfigResponse:
    """Get the site configuration for the frontend."""
    cfg = content_manager.site_config
    return SiteConfigResponse(
        title=cfg.title,
        description=cfg.description,
        pages=[PageConfig(id=p.id, title=p.title, file=p.file) for p in cfg.pages],
    )


async def get_page(
    session_factory: async_sessionmaker[AsyncSession],
    content_manager: ContentManager,
    page_id: str,
) -> PageResponse | None:
    """Get a top-level page from the cache."""
    cfg = content_manager.site_config
    page_cfg = next((p for p in cfg.pages if p.id == page_id), None)
    if page_cfg is None:
        return None

    if page_cfg.file is None:
        return None

    async with session_factory() as session:
        row = (
            await session.execute(select(PageCache).where(PageCache.page_id == page_id))
        ).scalar_one_or_none()

    if row is None:
        logger.warning("Page %s has a file but no cache entry", page_id)
        return None

    return PageResponse(id=page_id, title=row.title, rendered_html=row.rendered_html)
