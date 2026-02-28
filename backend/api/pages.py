"""Page API endpoints."""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_content_manager
from backend.filesystem.content_manager import ContentManager
from backend.pandoc.renderer import RenderError
from backend.schemas.page import PageResponse, SiteConfigResponse
from backend.services.page_service import get_page, get_site_config

logger = logging.getLogger(__name__)

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
    return page
