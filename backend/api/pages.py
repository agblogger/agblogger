"""Page API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import (
    get_content_manager,
    get_current_admin,
    get_session,
    get_session_factory,
)
from backend.filesystem.content_manager import ContentManager
from backend.models.user import AdminUser
from backend.schemas.admin import PAGE_ID_PATTERN
from backend.schemas.page import PageResponse, SiteConfigResponse, SubscriptionCompliance
from backend.services import subscription_service
from backend.services.analytics_service import fire_background_hit
from backend.services.page_service import get_page, get_site_config
from backend.services.subscription_service import PublicSubscriptionCompliance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pages", tags=["pages"])


def _privacy_policy_page(compliance: PublicSubscriptionCompliance | None) -> PageResponse:
    """Generate a fallback privacy policy page for the email subscription feature."""
    controller_html = ""
    if compliance is not None:
        if compliance.controller_name:
            contact_part = (
                f", contact: {compliance.controller_contact}"
                if compliance.controller_contact
                else ""
            )
            controller_html = (
                f"<h2>Data controller</h2><p>{compliance.controller_name}{contact_part}</p>"
            )
        elif compliance.controller_contact:
            controller_html = (
                f"<h2>Data controller contact</h2><p>{compliance.controller_contact}</p>"
            )

    html = (
        "<p>This policy explains how this blog handles your personal data when you subscribe"
        " to email notifications.</p>"
        "<h2>What we collect</h2>"
        "<p>When you subscribe, we collect your email address.</p>"
        "<h2>How we use it</h2>"
        "<p>Your email address is used only to notify you of new posts, based on your"
        " consent (GDPR Art. 6(1)(a)).</p>"
        "<h2>Data processor</h2>"
        "<p>Emails are delivered by <strong>Resend</strong> (Plus Five Five, Inc., USA) as our data"
        " processor. Your address is stored and managed by Resend. This involves a transfer"
        " of personal data outside the EEA under appropriate safeguards (Resend&rsquo;s"
        " DPA).</p>"
        "<h2>Retention</h2>"
        "<p>We keep your email address until you unsubscribe. Every email includes an"
        " unsubscribe link.</p>"
        "<h2>Your rights</h2>"
        "<p>Under applicable data protection law you have the right to access, rectify,"
        " erase, and port your data, to restrict or object to processing, and to withdraw"
        " consent at any time. You may also lodge a complaint with a supervisory"
        " authority.</p>" + controller_html
    )
    return PageResponse(id="privacy", title="Privacy Policy", rendered_html=html)


@router.get("", response_model=SiteConfigResponse)
async def site_config(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteConfigResponse:
    """Get site configuration including page list and whether subscriptions are enabled."""
    config = get_site_config(content_manager)
    compliance = await subscription_service.get_public_compliance(session)
    config.subscriptions_enabled = compliance is not None
    config.subscription_compliance = (
        SubscriptionCompliance(
            controller_name=compliance.controller_name,
            controller_contact=compliance.controller_contact,
            privacy_policy_url=compliance.privacy_policy_url,
        )
        if compliance is not None
        else None
    )
    return config


@router.get("/{page_id}", response_model=PageResponse)
async def get_page_endpoint(
    page_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
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
    if page is None and page_id == "privacy":
        compliance = await subscription_service.get_public_compliance(session)
        page = _privacy_policy_page(compliance)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fire_background_hit(
        request=request,
        session_factory=session_factory,
        path=f"/page/{page_id}",
        user=user,
    )
    return page
