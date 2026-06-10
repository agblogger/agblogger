"""Subscription orchestration: settings, subscribe/confirm, broadcasts.

Stores no subscriber PII. Resend is the system of record for contacts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.subscription import SubscriptionSettings
from backend.schemas.subscription import SubscriptionSettingsResponse
from backend.services import resend_client
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.services.subscription_email import build_confirmation_email
from backend.services.subscription_tokens import (
    create_confirm_token,
    normalize_email,
    verify_confirm_token,
)
from backend.utils.datetime import now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SEGMENT_NAME = "AgBlogger subscribers"
# from_name is intentionally NOT here: it is a display-name only, not a
# GDPR-compliance field, so it is optional even when enabling subscriptions.
_REQUIRED_TO_ENABLE = (
    "from_email",
    "controller_name",
    "controller_contact",
    "privacy_policy_url",
    "postal_address",
)


class EnablePreconditionError(Exception):
    """Raised when enabling is requested without the required compliance config.

    The API layer maps this to HTTP 422.
    """


class SubscriptionsDisabledError(Exception):
    """Subscriptions are disabled or not fully configured."""


async def _get_row(session: AsyncSession) -> SubscriptionSettings | None:
    result = await session.execute(select(SubscriptionSettings).limit(1))
    return result.scalar_one_or_none()


def decrypt_api_key(row: SubscriptionSettings, secret_key: str) -> str | None:
    if not row.resend_api_key_encrypted:
        return None
    return decrypt_value(row.resend_api_key_encrypted, secret_key)


async def update_settings(
    session: AsyncSession,
    *,
    secret_key: str,
    enabled: bool | None = None,
    api_key: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    controller_name: str | None = None,
    controller_contact: str | None = None,
    privacy_policy_url: str | None = None,
    postal_address: str | None = None,
) -> SubscriptionSettings:
    """Create/update the singleton, encrypting the key and enforcing the enable gate."""
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

    if api_key is not None and api_key != "":
        row.resend_api_key_encrypted = encrypt_value(api_key, secret_key)
    for field, value in (
        ("from_email", from_email),
        ("from_name", from_name),
        ("controller_name", controller_name),
        ("controller_contact", controller_contact),
        ("privacy_policy_url", privacy_policy_url),
        ("postal_address", postal_address),
    ):
        if value is not None:
            setattr(row, field, value)

    if enabled is True:
        try:
            await _prepare_enable(session, row, secret_key)
        except Exception:
            await session.rollback()
            raise
        row.enabled = True
    elif enabled is False:
        row.enabled = False

    row.updated_at = now_utc().isoformat()
    await session.commit()
    await session.refresh(row)
    return row


async def _prepare_enable(
    session: AsyncSession, row: SubscriptionSettings, secret_key: str
) -> None:
    """Validate compliance config and ensure a Resend segment exists before enabling."""
    if not row.resend_api_key_encrypted:
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    missing = [f for f in _REQUIRED_TO_ENABLE if not getattr(row, f)]
    if missing:
        raise EnablePreconditionError("Set these before enabling: " + ", ".join(missing))
    if not row.resend_segment_id:
        api_key = decrypt_api_key(row, secret_key)
        if api_key is None:
            raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
        # Accepted tradeoff: if the commit fails after this succeeds, the created
        # Resend segment is orphaned. Acceptable for this admin-only path (no data
        # loss / security impact).
        row.resend_segment_id = await resend_client.create_segment(
            api_key=api_key, name=_SEGMENT_NAME
        )


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
            segment_configured=False,
            subscriber_count=None,
        )
    count: int | None = None
    api_key = decrypt_api_key(row, secret_key)
    if api_key and row.resend_segment_id:
        try:
            count = await resend_client.count_contacts(
                api_key=api_key, segment_id=row.resend_segment_id
            )
        except resend_client.ResendError:
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
