"""Subscription orchestration: settings, subscribe/confirm, broadcasts.

Stores no subscriber PII. Resend is the system of record for contacts."""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_module
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from svix.webhooks import Webhook
from svix.webhooks import WebhookVerificationError as WebhookVerificationError

from backend.models.subscription import SubscriptionBroadcast, SubscriptionSettings
from backend.schemas.subscription import (
    BroadcastStatus,
    BroadcastSummary,
    BroadcastTrigger,
    SubscriptionSettingsResponse,
)
from backend.services import resend_client
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.services.subscription_email import build_broadcast_email, build_confirmation_email
from backend.services.subscription_tokens import (
    create_confirm_token,
    normalize_email,
    verify_confirm_token,
)
from backend.utils.datetime import now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_SEGMENT_NAME = "AgBlogger subscribers"
# Short-lived in-memory cache for the Resend contact count, keyed by segment id.
# Avoids walking all contact pages on every admin GET /settings poll.
# TTL of 30 s is short enough to reflect real changes quickly, long enough to
# avoid hammering the Resend API under aggressive polling.
_COUNT_CACHE_TTL = 30.0  # seconds
_count_cache: dict[str, tuple[float, int]] = {}


def _time() -> float:
    return _time_module.monotonic()


# Compliance fields are optional and control which parts of the GDPR notice
# are shown. The webhook is provisioned automatically while enabling.
_REQUIRED_TO_ENABLE = ("from_email",)
_WEBHOOK_EVENTS = ["contact.updated"]


class _Unset:
    pass


_UNSET = _Unset()
_StringUpdate = str | None | _Unset


@dataclass(frozen=True)
class PublicSubscriptionCompliance:
    controller_name: str | None
    controller_contact: str | None
    privacy_policy_url: str | None


class EnablePreconditionError(Exception):
    """Raised when enabling is requested without the required compliance config.

    The API layer maps this to HTTP 400.
    """


class SubscriptionsDisabledError(Exception):
    """Subscriptions are disabled or not fully configured."""


class WebhookProcessingError(Exception):
    """A verified webhook could not be processed and should be retried."""


async def _get_row(session: AsyncSession) -> SubscriptionSettings | None:
    result = await session.execute(select(SubscriptionSettings).limit(1))
    return result.scalar_one_or_none()


async def is_enabled(session: AsyncSession) -> bool:
    """True iff subscriptions are configured and enabled."""
    row = await _get_row(session)
    return bool(row and row.enabled)


async def get_public_compliance(
    session: AsyncSession,
) -> PublicSubscriptionCompliance | None:
    """Return compliance details when subscriptions are enabled; None otherwise.

    Fields may be None when not configured — the subscribe page renders each
    part of the GDPR notice conditionally.
    """
    row = await _get_row(session)
    if row is None or not row.enabled:
        return None
    return PublicSubscriptionCompliance(
        controller_name=row.controller_name or None,
        controller_contact=row.controller_contact or None,
        privacy_policy_url=row.privacy_policy_url or None,
    )


def decrypt_api_key(row: SubscriptionSettings, secret_key: str) -> str | None:
    if not row.resend_api_key_encrypted:
        return None
    return decrypt_value(row.resend_api_key_encrypted, secret_key)


def decrypt_webhook_secret(row: SubscriptionSettings, secret_key: str) -> str | None:
    if not row.resend_webhook_secret_encrypted:
        return None
    return decrypt_value(row.resend_webhook_secret_encrypted, secret_key)


async def update_settings(
    session: AsyncSession,
    *,
    secret_key: str,
    enabled: bool | None = None,
    api_key: str | None = None,
    webhook_secret: str | None = None,
    webhook_url: str | None = None,
    from_email: _StringUpdate = _UNSET,
    from_name: _StringUpdate = _UNSET,
    controller_name: _StringUpdate = _UNSET,
    controller_contact: _StringUpdate = _UNSET,
    privacy_policy_url: _StringUpdate = _UNSET,
    postal_address: _StringUpdate = _UNSET,
) -> SubscriptionSettings:
    """Create/update the singleton and enforce the enable gate.

    ``webhook_secret`` is an internal setup/testing escape hatch. The admin API
    provisions the Resend webhook automatically and never accepts this value.
    """
    row = await _get_row(session)
    if row is None:
        row = SubscriptionSettings(id=1)
        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(SubscriptionSettings).limit(1))
            row = result.scalar_one()

    api_key_changed = (
        api_key is not None and api_key != "" and api_key != decrypt_api_key(row, secret_key)
    )
    if api_key_changed:
        row.resend_segment_id = None
        row.resend_webhook_secret_encrypted = None
    if api_key is not None and api_key != "":
        row.resend_api_key_encrypted = encrypt_value(api_key, secret_key)
    if webhook_secret is not None and webhook_secret != "":
        row.resend_webhook_secret_encrypted = encrypt_value(webhook_secret, secret_key)
    for field, value in (
        ("from_email", from_email),
        ("from_name", from_name),
        ("controller_name", controller_name),
        ("controller_contact", controller_contact),
        ("privacy_policy_url", privacy_policy_url),
        ("postal_address", postal_address),
    ):
        if not isinstance(value, _Unset):
            setattr(row, field, value)

    target_enabled = row.enabled if enabled is None else enabled
    if target_enabled:
        try:
            await _prepare_enable(session, row, secret_key, webhook_url)
        except Exception:
            await session.rollback()
            raise
    row.enabled = target_enabled

    row.updated_at = now_utc().isoformat()
    await session.commit()
    await session.refresh(row)
    return row


async def _prepare_enable(
    session: AsyncSession,
    row: SubscriptionSettings,
    secret_key: str,
    webhook_url: str | None,
) -> None:
    """Validate required config and ensure the Resend resources exist before enabling."""
    if not row.resend_api_key_encrypted:
        # Fast path: avoids the decryption call when no key is configured at all.
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    missing = [f for f in _REQUIRED_TO_ENABLE if not getattr(row, f)]
    if missing:
        labels = {"from_email": "from_email"}
        raise EnablePreconditionError(
            "Set these before enabling: " + ", ".join(labels[field] for field in missing)
        )
    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    if row.resend_segment_id:
        exists = await resend_client.check_segment_exists(
            api_key=api_key, segment_id=row.resend_segment_id
        )
        if not exists:
            row.resend_segment_id = None
    if not row.resend_segment_id:
        # Accepted tradeoff: if the commit fails after this succeeds, the created
        # Resend segment is orphaned. Acceptable for this admin-only path (no data
        # loss / security impact).
        row.resend_segment_id = await resend_client.create_segment(
            api_key=api_key, name=_SEGMENT_NAME
        )
    if not row.resend_webhook_secret_encrypted:
        await _try_provision_webhook(row, api_key, secret_key, webhook_url)


async def _try_provision_webhook(
    row: SubscriptionSettings,
    api_key: str,
    secret_key: str,
    webhook_url: str | None,
) -> None:
    """Best-effort webhook setup; retries on each enabled settings update."""
    if not webhook_url or urlsplit(webhook_url).scheme != "https":
        logger.info(
            "Skipping Resend webhook setup because the current site URL is not public HTTPS"
        )
        return
    try:
        signing_secret = await resend_client.create_webhook(
            api_key=api_key,
            endpoint=webhook_url,
            events=_WEBHOOK_EVENTS,
        )
    except resend_client.ResendError:
        logger.warning(
            "Could not configure Resend unsubscribe webhook; will retry on the next "
            "enabled subscription settings update",
            exc_info=True,
        )
        return
    row.resend_webhook_secret_encrypted = encrypt_value(signing_secret, secret_key)


async def build_settings_response(
    session: AsyncSession, secret_key: str
) -> SubscriptionSettingsResponse:
    row = await _get_row(session)
    if row is None:
        return SubscriptionSettingsResponse(
            enabled=False,
            from_email=None,
            from_name=None,
            controller_name=None,
            controller_contact=None,
            privacy_policy_url=None,
            postal_address=None,
            key_configured=False,
            webhook_secret_configured=False,
            segment_configured=False,
            subscriber_count=None,
        )
    count: int | None = None
    api_key = decrypt_api_key(row, secret_key)
    if api_key and row.resend_segment_id:
        cached = _count_cache.get(row.resend_segment_id)
        if cached is not None:
            ts, cached_count = cached
            if _time() - ts < _COUNT_CACHE_TTL:
                count = cached_count
        if count is None:
            try:
                count = await resend_client.count_contacts(
                    api_key=api_key, segment_id=row.resend_segment_id
                )
                _count_cache[row.resend_segment_id] = (_time(), count)
            except resend_client.ResendError:
                logger.warning(
                    "Failed to count Resend contacts for segment %s",
                    row.resend_segment_id,
                    exc_info=True,
                )
                count = None
    return SubscriptionSettingsResponse(
        enabled=row.enabled,
        from_email=row.from_email,
        from_name=row.from_name,
        controller_name=row.controller_name,
        controller_contact=row.controller_contact,
        privacy_policy_url=row.privacy_policy_url,
        postal_address=row.postal_address,
        key_configured=bool(row.resend_api_key_encrypted),
        webhook_secret_configured=bool(row.resend_webhook_secret_encrypted),
        segment_configured=bool(row.resend_segment_id),
        subscriber_count=count,
    )


def _from_header(row: SubscriptionSettings) -> str:
    from_email = row.from_email or ""
    if row.from_name and from_email:
        return f"{row.from_name} <{from_email}>"
    return from_email


async def subscribe(session: AsyncSession, *, secret_key: str, email: str, base_url: str) -> None:
    """Send a confirmation email. Persists nothing. Raises if not configured/enabled."""
    row = await _get_row(session)
    if row is None or not row.enabled:
        raise SubscriptionsDisabledError()
    api_key = decrypt_api_key(row, secret_key)
    from_email = row.from_email
    if api_key is None or not from_email:
        raise SubscriptionsDisabledError()
    controller = row.controller_name or from_email
    token = create_confirm_token(email, secret_key)
    confirm_url = f"{base_url.rstrip('/')}/subscribe/confirm?token={token}"
    html, text = build_confirmation_email(confirm_url=confirm_url, controller_name=controller)
    await resend_client.send_email(
        api_key=api_key,
        from_=_from_header(row),
        to=normalize_email(email),
        subject=f"Confirm your subscription to {controller}",
        html=html,
        text=text,
    )


async def send_test_email(session: AsyncSession, *, secret_key: str, to: str) -> None:
    """Send a test email to verify Resend config.

    Intentionally does NOT require ``enabled=True`` so the admin can verify the
    Resend configuration during setup before enabling subscriptions.

    Raises SubscriptionsDisabledError if unconfigured; ResendError on send failure.
    """
    row = await _get_row(session)
    if row is None:
        raise SubscriptionsDisabledError()
    api_key = decrypt_api_key(row, secret_key)
    from_email = row.from_email
    if api_key is None or not from_email:
        raise SubscriptionsDisabledError()
    await resend_client.send_email(
        api_key=api_key,
        from_=_from_header(row),
        to=to,
        subject="AgBlogger test email",
        html="<p>This is a test email from your blog.</p>",
        text="This is a test email from your blog.",
    )


async def confirm(session: AsyncSession, *, secret_key: str, token: str) -> bool:
    """Verify the token and create the Resend contact. Returns False on bad token."""
    email = verify_confirm_token(token, secret_key)
    if email is None:
        return False
    row = await _get_row(session)
    if row is None or not row.enabled:
        return False
    segment_id = row.resend_segment_id
    if not segment_id:
        return False
    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        return False
    await resend_client.create_contact(api_key=api_key, segment_id=segment_id, email=email)
    return True


# ── Broadcast firing + once-guard ledger ──────────────────────────────────────

_broadcast_tasks: set[asyncio.Task[None]] = set()
_MAX_BROADCAST_TASKS = 16


async def list_broadcasts(session: AsyncSession, *, limit: int = 100) -> list[BroadcastSummary]:
    """Return recent broadcast ledger rows (most recent first) for the admin view."""
    result = await session.execute(
        select(SubscriptionBroadcast).order_by(SubscriptionBroadcast.id.desc()).limit(limit)
    )
    return [
        BroadcastSummary(
            id=r.id,
            request_id=r.request_id,
            post_path=r.post_path,
            post_title=r.post_title,
            resend_broadcast_id=r.resend_broadcast_id,
            trigger=r.trigger,
            status=r.status,
            sent_at=r.sent_at,
            error=r.error,
        )
        for r in result.scalars().all()
    ]


async def already_broadcast(session: AsyncSession, post_path: str) -> bool:
    """Return True if a successful broadcast was already sent for this post."""
    result = await session.execute(
        select(SubscriptionBroadcast)
        .where(
            SubscriptionBroadcast.post_path == post_path,
            SubscriptionBroadcast.status == BroadcastStatus.SENT,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def update_broadcast_post_path(
    session: AsyncSession, *, old_post_path: str, new_post_path: str
) -> None:
    """Keep broadcast ledger references aligned when a post is renamed."""
    await session.execute(
        update(SubscriptionBroadcast)
        .where(SubscriptionBroadcast.post_path == old_post_path)
        .values(post_path=new_post_path)
    )


async def send_broadcast(
    session: AsyncSession,
    *,
    secret_key: str,
    post_path: str,
    post_title: str,
    post_html: str,
    post_url: str,
    trigger: BroadcastTrigger,
    request_id: str | None = None,
) -> None:
    """Send one broadcast via Resend and record a ledger row. Never raises."""
    row = await _get_row(session)
    record = SubscriptionBroadcast(
        request_id=request_id or str(uuid4()),
        post_path=post_path,
        post_title=post_title,
        trigger=trigger,
        status=BroadcastStatus.FAILED,
        sent_at=now_utc().isoformat(),
        error=None,
    )
    try:
        if row is None or not row.enabled or not row.resend_segment_id:
            record.error = "Subscriptions not configured"
        else:
            api_key = decrypt_api_key(row, secret_key)
            from_email = row.from_email
            segment_id = row.resend_segment_id
            if api_key is None or not from_email or not segment_id:
                record.error = "Subscriptions not configured"
            else:
                html, text = await build_broadcast_email(
                    post_url=post_url,
                    post_title=post_title,
                    post_html=post_html,
                    controller_name=row.controller_name or from_email,
                    postal_address=row.postal_address or "",
                )
                try:
                    broadcast_id = await resend_client.create_and_send_broadcast(
                        api_key=api_key,
                        segment_id=segment_id,
                        from_=_from_header(row),
                        subject=post_title,
                        html=html,
                        text=text,
                    )
                except resend_client.BroadcastSendError as exc:
                    # Create succeeded but send failed — record the broadcast id so
                    # it can be found in Resend for manual cleanup/retry.
                    # NOTE: manual retrigger may double-send if the original broadcast
                    # was already delivered before the send-POST error occurred.
                    record.resend_broadcast_id = exc.broadcast_id
                    logger.warning(
                        "Broadcast %s created but send failed for %s",
                        exc.broadcast_id,
                        post_path,
                        exc_info=True,
                    )
                    raise
                record.resend_broadcast_id = broadcast_id
                record.status = BroadcastStatus.SENT
    except resend_client.ResendError as exc:
        record.error = str(exc)
    except Exception:  # never let a broadcast crash the caller
        logger.error("Unexpected broadcast failure for %s", post_path, exc_info=True)
        record.error = "Internal error"
    session.add(record)
    await session.commit()


def fire_post_broadcast(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    secret_key: str,
    post_path: str,
    post_title: str,
    post_html: str,
    post_url: str,
    trigger: BroadcastTrigger,
    enforce_once_guard: bool,
    request_id: str | None = None,
) -> bool:
    """Schedule a fire-and-forget broadcast. Used by the publish hook + manual trigger."""
    if len(_broadcast_tasks) >= _MAX_BROADCAST_TASKS:
        logger.warning("Dropping broadcast for %s: task limit reached", post_path)
        return False

    resolved_request_id = request_id or str(uuid4())

    async def _run() -> None:
        try:
            async with session_factory() as session:
                # Known limitation: two concurrent fires for the same post could both
                # pass this check before either commits a "sent" row (no DB lock).
                # Acceptable — publish transitions are admin-only and rare.
                if enforce_once_guard and await already_broadcast(session, post_path):
                    return
                await send_broadcast(
                    session,
                    secret_key=secret_key,
                    post_path=post_path,
                    post_title=post_title,
                    post_html=post_html,
                    post_url=post_url,
                    trigger=trigger,
                    request_id=resolved_request_id,
                )
        except Exception:
            logger.error("Background broadcast failed for %s", post_path, exc_info=True)

    task = asyncio.create_task(_run())
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)
    return True


async def handle_resend_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    headers: dict[str, str],
    secret_key: str,
) -> None:
    """Verify Resend webhook signature and process the event.

    Raises WebhookVerificationError on bad signature — caller maps this to 400.
    Processing failures raise WebhookProcessingError or ResendError so the
    endpoint can return a retryable response.
    """
    row = await _get_row(session)
    if row is None or not row.resend_webhook_secret_encrypted:
        raise WebhookProcessingError("Resend webhook secret is not configured")

    webhook_secret = decrypt_webhook_secret(row, secret_key)
    if webhook_secret is None:
        raise WebhookProcessingError("Resend webhook secret could not be decrypted")

    # Raises WebhookVerificationError on bad/expired signature — propagated to caller.
    # The Svix library also parses JSON inside verify; JSONDecodeError (a ValueError
    # subclass) from malformed bodies is caught here and re-raised as a retryable
    # WebhookProcessingError so the caller can return 503 rather than 500.
    try:
        Webhook(webhook_secret).verify(raw_body, headers)
    except WebhookVerificationError:
        raise
    except ValueError, UnicodeDecodeError:
        raise WebhookProcessingError("Resend webhook body is malformed") from None

    try:
        payload = json.loads(raw_body)
    except ValueError, UnicodeDecodeError:
        raise WebhookProcessingError("Resend webhook body is malformed") from None

    if payload.get("type") != "contact.updated":
        return

    data = payload.get("data")
    if not isinstance(data, dict):
        raise WebhookProcessingError("contact.updated missing data")
    if data.get("unsubscribed") is not True:
        return

    contact_id = data.get("id")

    if not isinstance(contact_id, str) or not contact_id:
        raise WebhookProcessingError("unsubscribed contact.updated missing contact id")

    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        raise WebhookProcessingError("Resend API key is not configured")

    try:
        await resend_client.delete_contact(api_key=api_key, contact_id=contact_id)
        logger.info("Permanently deleted unsubscribed contact %s from Resend", contact_id)
    except resend_client.ResendError as exc:
        logger.warning("Resend webhook: failed to delete contact %s: %s", contact_id, exc)
        raise


async def close_broadcast_tasks() -> None:
    """Drain in-flight broadcast tasks on shutdown (short timeout).

    Called from the app lifespan shutdown so a graceful stop lets pending
    Resend broadcasts finish and commit their ledger row.
    """
    if _broadcast_tasks:
        await asyncio.wait(_broadcast_tasks, timeout=3.0)
