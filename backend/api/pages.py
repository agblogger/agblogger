"""Page API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import get_content_manager, get_current_admin, get_session_factory
from backend.filesystem.content_manager import ContentManager
from backend.models.user import AdminUser
from backend.schemas.admin import PAGE_ID_PATTERN
from backend.schemas.page import PageResponse, SiteConfigResponse
from backend.services.analytics_service import fire_background_hit
from backend.services.page_service import get_page, get_site_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pages", tags=["pages"])


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
    user: Annotated[AdminUser | None, Depends(get_current_admin)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
) -> PageResponse:
    """Get a top-level page with cached HTML."""
    if not PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page ID")
    try:
        page = await get_page(session_factory, content_manager, page_id)
    except SQLAlchemyError:
        logger.exception("DB error loading page %s", page_id)
        raise HTTPException(status_code=503, detail="Page temporarily unavailable") from None
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fire_background_hit(
        request=request,
        session_factory=session_factory,
        path=f"/page/{page_id}",
        user=user,
    )
    return page
