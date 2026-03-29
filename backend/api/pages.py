"""Page API endpoints."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import get_content_manager, get_current_admin, get_session_factory
from backend.filesystem.content_manager import ContentManager
from backend.models.user import AdminUser
from backend.schemas.page import PageResponse, SiteConfigResponse
from backend.services.analytics_service import fire_background_hit
from backend.services.page_service import get_page, get_site_config

_PAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

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
    """Get a top-level page with rendered HTML."""
    if not _PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page ID")
    page = await get_page(session_factory, content_manager, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fire_background_hit(
        request=request,
        session_factory=session_factory,
        path=f"/page/{page_id}",
        user=user,
    )
    return page
