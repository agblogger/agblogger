"""Subscription endpoints: public subscribe/confirm + admin management."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import (
    get_session,
    get_session_factory,
    get_settings,
    require_admin,
)
from backend.config import Settings
from backend.models.post import PostCache
from backend.models.subscription import SubscriptionBroadcast
from backend.models.user import AdminUser
from backend.net_utils import is_trusted_proxy
from backend.schemas.subscription import (
    BroadcastListResponse,
    BroadcastSummary,
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
)
from backend.utils.slug import file_path_to_slug

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api", tags=["subscriptions"])
page_router = APIRouter(tags=["subscriptions"])  # backend-served HTML (no /api prefix)
admin_router = APIRouter(prefix="/api/admin/subscriptions", tags=["subscriptions-admin"])

_SUBSCRIBE_BURST = (3, 60)  # 3 / minute
_SUBSCRIBE_SUSTAINED = (10, 3600)  # 10 / hour


def _client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    host = request.client.host if request.client and request.client.host else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and is_trusted_proxy(host, settings.trusted_proxy_ips):
        return forwarded.split(",")[0].strip()
    return host


def _enforce_subscribe_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    ip = _client_ip(request)
    for limit, window in (_SUBSCRIBE_BURST, _SUBSCRIBE_SUSTAINED):
        key = f"subscribe:{window}:{ip}"
        limited, retry_after = limiter.is_limited(key, limit, window)
        if limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
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


@page_router.get("/subscribe/confirm", response_class=HTMLResponse)
async def confirm_endpoint(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    ok = False
    try:
        ok = await subscription_service.confirm(
            session, secret_key=settings.secret_key, token=token
        )
    except resend_client.ResendError:
        logger.warning("Confirm contact creation failed", exc_info=True)
    message = (
        "You're subscribed! Thanks for confirming."
        if ok
        else "This confirmation link is invalid or has expired."
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Subscription</title></head>"
        "<body style='font-family:system-ui,Arial,sans-serif;max-width:480px;margin:64px auto;"
        f"text-align:center'><p>{message}</p><p><a href='/'>Back to the blog</a></p></body></html>"
    )
    return HTMLResponse(content=html, status_code=200 if ok else 400)


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
        await subscription_service.update_settings(
            session,
            secret_key=settings.secret_key,
            enabled=body.enabled,
            api_key=body.api_key,
            from_email=body.from_email,
            from_name=body.from_name,
            controller_name=body.controller_name,
            controller_contact=body.controller_contact,
            privacy_policy_url=body.privacy_policy_url,
            postal_address=body.postal_address,
        )
    except EnablePreconditionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except resend_client.ResendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
    result = await session.execute(
        select(SubscriptionBroadcast).order_by(SubscriptionBroadcast.id.desc()).limit(100)
    )
    rows = result.scalars().all()
    return BroadcastListResponse(
        broadcasts=[
            BroadcastSummary(
                id=r.id,
                post_path=r.post_path,
                post_title=r.post_title,
                resend_broadcast_id=r.resend_broadcast_id,
                trigger=r.trigger,
                status=r.status,
                sent_at=r.sent_at,
                error=r.error,
            )
            for r in rows
        ]
    )


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
    subscription_service.fire_post_broadcast(
        session_factory,
        secret_key=settings.secret_key,
        post_path=post.file_path,
        post_title=post.title,
        post_html=post.rendered_html or "",
        post_url=post_url,
        trigger="manual",
        enforce_once_guard=False,
    )
    return {"message": "Broadcast started"}
