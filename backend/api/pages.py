"""Page API endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import get_content_manager, get_current_user, get_session_factory
from backend.filesystem.content_manager import ContentManager
from backend.models.user import User
from backend.pandoc.renderer import RenderError
from backend.schemas.page import PageResponse, SiteConfigResponse
from backend.services.analytics_service import record_hit
from backend.services.page_service import get_page, get_site_config

logger = logging.getLogger(__name__)

_PAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

router = APIRouter(prefix="/api/pages", tags=["pages"])

# Strong references to fire-and-forget analytics tasks, preventing GC before completion.
_background_tasks: set[asyncio.Task[None]] = set()


@router.get("", response_model=SiteConfigResponse)
async def site_config(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
) -> SiteConfigResponse:
    """Get site configuration including page list."""
    return get_site_config(content_manager)


@router.get("/{page_id}", response_model=PageResponse)
async def get_page_endpoint(
    page_id: str,
    request: Request,
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    user: Annotated[User | None, Depends(get_current_user)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
) -> PageResponse:
    """Get a top-level page with rendered HTML."""
    if not _PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page ID")
    try:
        page = await get_page(content_manager, page_id)
    except RenderError as exc:
        logger.error("Pandoc rendering failed for page %s: %s", page_id, exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    user_agent = request.headers.get("user-agent", "")

    async def _do_hit() -> None:
        try:
            async with session_factory() as session:
                await record_hit(
                    session=session,
                    path=f"/page/{page_id}",
                    client_ip=client_ip,
                    user_agent=user_agent,
                    user=user,
                )
        except Exception:
            logger.warning("Background analytics hit failed for /page/%s", page_id, exc_info=True)

    task = asyncio.create_task(_do_hit())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return page
