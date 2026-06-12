"""Subscription endpoints: public subscribe/confirm + admin management."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from svix.webhooks import WebhookVerificationError

from agblogger_core import file_path_to_slug
from backend.api.deps import (
    get_session,
    get_session_factory,
    get_settings,
    require_admin,
)
from backend.api.rate_limit import client_ip_from_request, enforce_rate_limit
from backend.config import Settings
from backend.exceptions import InternalServerError
from backend.models.post import PostCache
from backend.models.user import AdminUser
from backend.schemas.subscription import (
    BroadcastListResponse,
    BroadcastTrigger,
    SendTestEmailRequest,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionSettingsResponse,
    SubscriptionSettingsUpdate,
    TriggerBroadcastRequest,
)
from backend.services import resend_client, subscription_service
from backend.services.subscription_service import (
    EnablePreconditionError,
    SubscriptionsDisabledError,
    WebhookProcessingError,
)

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api", tags=["subscriptions"])
page_router = APIRouter(tags=["subscriptions"])  # backend-served HTML (no /api prefix)
admin_router = APIRouter(prefix="/api/admin/subscriptions", tags=["subscriptions-admin"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_SUBSCRIBE_BURST = (3, 60)  # 3 / minute
_SUBSCRIBE_SUSTAINED = (10, 3600)  # 10 / hour


def _enforce_subscribe_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    settings: Settings = request.app.state.settings
    ip = client_ip_from_request(request, settings.trusted_proxy_ips)
    for limit, window in (_SUBSCRIBE_BURST, _SUBSCRIBE_SUSTAINED):
        enforce_rate_limit(
            limiter,
            f"subscribe:{window}:{ip}",
            limit,
            window,
            "Too many requests. Please try again later.",
        )
    for _limit, window in (_SUBSCRIBE_BURST, _SUBSCRIBE_SUSTAINED):
        limiter.add_failure(f"subscribe:{window}:{ip}", window)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@public_router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe_endpoint(
    body: SubscribeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscribeResponse:
    _enforce_subscribe_rate_limit(request)
    try:
        await subscription_service.subscribe(
            session,
            secret_key=settings.secret_key,
            email=str(body.email),
            base_url=_base_url(request),
        )
    except SubscriptionsDisabledError as exc:
        raise HTTPException(status_code=404, detail="Subscriptions are not available") from exc
    except resend_client.ResendError:
        logger.warning("Subscribe confirmation send failed", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Subscriptions are temporarily unavailable"
        ) from None
    return SubscribeResponse()


_CONFIRM_RETRY_MESSAGE = (
    "We couldn't complete your subscription right now. "
    "Please click the link again in a few minutes."
)


def _confirmation_page(message: str, status_code: int) -> HTMLResponse:
    # message is always a static constant (never user input), so no escaping needed.
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Subscription</title></head>"
        "<body style='font-family:system-ui,Arial,sans-serif;max-width:480px;margin:64px auto;"
        f"text-align:center'><p>{message}</p>"
        "<p><a href='/'>Back to the blog</a></p></body></html>"
    )
    return HTMLResponse(content=html, status_code=status_code)


@page_router.get("/subscribe/confirm", response_class=HTMLResponse)
async def confirm_endpoint(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    ok = False
    retryable = False
    try:
        ok = await subscription_service.confirm(
            session, secret_key=settings.secret_key, token=token
        )
    except resend_client.ResendError:
        logger.warning("Confirm contact creation failed (Resend transient error)", exc_info=True)
        retryable = True
    except InternalServerError:
        # Raised by decrypt_value on SECRET_KEY rotation; do not leak details.
        logger.error("Confirm contact creation failed (internal error)", exc_info=True)
        retryable = True

    if retryable:
        return _confirmation_page(_CONFIRM_RETRY_MESSAGE, 503)

    message = (
        "You're subscribed! Thanks for confirming."
        if ok
        else "This confirmation link is invalid or has expired."
    )
    return _confirmation_page(message, 200 if ok else 400)


@admin_router.get("/settings", response_model=SubscriptionSettingsResponse)
async def get_settings_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> SubscriptionSettingsResponse:
    return await subscription_service.build_settings_response(session, settings.secret_key)


@admin_router.put("/settings", response_model=SubscriptionSettingsResponse)
async def update_settings_endpoint(
    body: SubscriptionSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> SubscriptionSettingsResponse:
    try:
        updates = body.model_dump(exclude_unset=True)
        await subscription_service.update_settings(
            session,
            secret_key=settings.secret_key,
            **updates,
        )
    except EnablePreconditionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except resend_client.ResendError as exc:
        # Use 400 so the error detail (e.g. "Invalid API key") reaches the admin UI.
        raise HTTPException(status_code=400, detail=f"Resend error: {exc}") from exc
    return await subscription_service.build_settings_response(session, settings.secret_key)


@admin_router.post("/test")
async def test_email_endpoint(
    body: SendTestEmailRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, str]:
    try:
        await subscription_service.send_test_email(
            session, secret_key=settings.secret_key, to=str(body.email)
        )
    except SubscriptionsDisabledError as exc:
        raise HTTPException(
            status_code=400, detail="Configure the API key and from-address first"
        ) from exc
    except resend_client.ResendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": "Test email sent"}


@admin_router.get("/broadcasts", response_model=BroadcastListResponse)
async def list_broadcasts_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> BroadcastListResponse:
    return BroadcastListResponse(broadcasts=await subscription_service.list_broadcasts(session))


@admin_router.post("/broadcasts", status_code=status.HTTP_202_ACCEPTED)
async def trigger_broadcast_endpoint(
    body: TriggerBroadcastRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, str]:
    result = await session.execute(select(PostCache).where(PostCache.file_path == body.post_path))
    post = result.scalar_one_or_none()
    if post is None or post.is_draft:
        raise HTTPException(status_code=404, detail="Published post not found")
    post_url = f"{_base_url(request)}/post/{file_path_to_slug(post.file_path)}"
    scheduled = subscription_service.fire_post_broadcast(
        session_factory,
        secret_key=settings.secret_key,
        post_path=post.file_path,
        post_title=post.title,
        post_html=post.rendered_html or "",
        post_url=post_url,
        trigger=BroadcastTrigger.MANUAL,
        enforce_once_guard=False,
    )
    if not scheduled:
        raise HTTPException(
            status_code=503,
            detail="Broadcast capacity is temporarily unavailable. Please try again.",
        )
    return {"message": "Broadcast started"}


@webhook_router.post("/resend")
async def resend_webhook_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    raw_body = await request.body()
    try:
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=raw_body,
            headers=dict(request.headers),
            secret_key=settings.secret_key,
        )
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from None
    except WebhookProcessingError, resend_client.ResendError:
        logger.warning("Resend unsubscribe deletion failed", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Webhook processing temporarily unavailable"
        ) from None
    except Exception:
        logger.warning("Resend webhook processing error", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Webhook processing temporarily unavailable"
        ) from None
    return {}
