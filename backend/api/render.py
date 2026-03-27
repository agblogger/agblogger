"""Render API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import require_admin
from backend.models.user import AdminUser
from backend.pandoc.renderer import RenderError, render_markdown, rewrite_relative_urls

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/render", tags=["render"])


class RenderRequest(BaseModel):
    """Markdown render request."""

    markdown: str = Field(max_length=500_000)
    file_path: str | None = None


class RenderResponse(BaseModel):
    """Rendered HTML response."""

    html: str


@router.post("/preview", response_model=RenderResponse)
async def preview(
    body: RenderRequest,
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> RenderResponse:
    """Render markdown to HTML for preview."""
    try:
        html = await render_markdown(body.markdown)
    except RenderError as exc:
        logger.error("Pandoc rendering failed in preview: %s", exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc
    if body.file_path is not None:
        html = rewrite_relative_urls(html, body.file_path)
    return RenderResponse(html=html)
