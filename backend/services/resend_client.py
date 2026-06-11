"""Thin async boundary over the Resend HTTP API. Verify exact paths against
https://resend.com/docs/api-reference (Audiences→Segments rename in progress)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.resend.com"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_client_instance: httpx.AsyncClient | None = None


class ResendError(Exception):
    """A Resend API call failed. Message is safe to show to the admin."""


class BroadcastSendError(ResendError):
    """Broadcast was created in Resend but the send POST failed.

    Carries the broadcast id so callers can record it in the ledger for
    manual recovery — without the id the orphan broadcast is unrecoverable.

    NOTE: If a manual retry is triggered after this error, there is a risk of
    double-sending: the original broadcast may have been delivered by Resend
    before the send-POST error was observed.  Operators should check the Resend
    dashboard for the broadcast_id before retrying.
    """

    def __init__(self, message: str, broadcast_id: str) -> None:
        super().__init__(message)
        self.broadcast_id = broadcast_id


def _get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first call.

    The lazy init is race-free only because every caller runs as a coroutine on
    the single event loop: this function has no ``await`` between the ``None``
    check and the assignment, so cooperative scheduling cannot interleave two
    invocations there. This is NOT a general "asyncio is single-threaded"
    guarantee -- sync (``def``) routes and ``run_in_executor`` run in a thread
    pool, where the check-then-set would race. If any caller is ever moved off
    the event loop, guard this with an ``asyncio.Lock`` (or a thread lock).
    The global is reset to None only by close_resend_client(), which runs at
    shutdown after all in-flight tasks have completed.
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client_instance


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _extract_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("message")
            if isinstance(message, str):
                return message
    except ValueError:
        pass
    return f"Resend returned HTTP {response.status_code}"


def _parse_json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ResendError("Unexpected response from the email provider") from exc
    return data if isinstance(data, dict) else {}


async def _post(api_key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await _get_client().post(
            f"{_API_BASE}{path}", json=payload, headers=_headers(api_key)
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend request to %s failed: %s", path, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    return _parse_json_object(response)


async def _get(api_key: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    try:
        response = await _get_client().get(
            f"{_API_BASE}{path}", params=params, headers=_headers(api_key)
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend request to %s failed: %s", path, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    return _parse_json_object(response)


async def send_email(
    *, api_key: str, from_: str, to: str, subject: str, html: str, text: str
) -> str:
    """Send one transactional email (confirmation / test). Returns the email id."""
    data = await _post(
        api_key,
        "/emails",
        {"from": from_, "to": [to], "subject": subject, "html": html, "text": text},
    )
    return str(data.get("id", ""))


async def create_contact(*, api_key: str, segment_id: str, email: str) -> None:
    """Add a confirmed contact to the Resend segment/audience."""
    # Treat "already exists" as success so confirm is idempotent.
    try:
        await _post(
            api_key,
            f"/audiences/{segment_id}/contacts",
            {"email": email, "unsubscribed": False},
        )
    except ResendError as exc:
        if "already exists" in str(exc).lower():
            return
        raise


async def delete_contact(*, api_key: str, audience_id: str, contact_id: str) -> None:
    """Permanently delete a contact from the Resend audience. Treats 404 as success."""
    try:
        response = await _get_client().delete(
            f"{_API_BASE}/audiences/{audience_id}/contacts/{contact_id}",
            headers=_headers(api_key),
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend delete contact %s failed: %s", contact_id, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code == 404:
        return
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))


async def create_segment(*, api_key: str, name: str) -> str:
    """Create a segment/audience and return its id."""
    data = await _post(api_key, "/audiences", {"name": name})
    segment_id = str(data.get("id", ""))
    if not segment_id:
        raise ResendError("Resend did not return a segment id")
    return segment_id


async def check_segment_exists(*, api_key: str, segment_id: str) -> bool:
    """Return True if the segment exists in Resend, False if it has been deleted.

    Re-raises ResendError for non-404 failures (auth errors, network errors, etc.)
    so callers cannot accidentally swallow real problems.
    """
    # Cannot use _get() here: it raises ResendError on all 4xx including 404.
    # We need to distinguish 404 (segment gone) from other errors (auth, network).
    try:
        response = await _get_client().get(
            f"{_API_BASE}/audiences/{segment_id}",
            headers=_headers(api_key),
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend request to /audiences/%s failed: %s", segment_id, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    return True


async def create_and_send_broadcast(
    *, api_key: str, segment_id: str, from_: str, subject: str, html: str, text: str
) -> str:
    """Create a broadcast to the segment and send it now. Returns the broadcast id.

    If the create POST succeeds but the send POST fails, raises BroadcastSendError
    (a subclass of ResendError) carrying the broadcast_id so callers can record it
    in the ledger for manual recovery.
    """
    created = await _post(
        api_key,
        "/broadcasts",
        {
            "audience_id": segment_id,
            "from": from_,
            "subject": subject,
            "html": html,
            "text": text,
        },
    )
    broadcast_id = str(created.get("id", ""))
    if not broadcast_id:
        raise ResendError("Resend did not return a broadcast id")
    try:
        await _post(api_key, f"/broadcasts/{broadcast_id}/send", {})
    except ResendError as exc:
        raise BroadcastSendError(str(exc), broadcast_id=broadcast_id) from exc
    return broadcast_id


async def count_contacts(*, api_key: str, segment_id: str) -> int:
    """Return the number of contacts in the segment."""
    count = 0
    after: str | None = None
    while True:
        params = {"limit": "100"}
        if after is not None:
            params["after"] = after
        data = await _get(api_key, f"/audiences/{segment_id}/contacts", params)
        items = data.get("data", [])
        if not isinstance(items, list):
            raise ResendError("Unexpected response from the email provider")
        count += len(items)
        if data.get("has_more") is not True:
            return count
        if not items or not isinstance(items[-1], dict):
            raise ResendError("Unexpected response from the email provider")
        next_after = items[-1].get("id")
        if not isinstance(next_after, str) or not next_after or next_after == after:
            raise ResendError("Unexpected response from the email provider")
        after = next_after


async def close_resend_client() -> None:
    """Close the shared client during app shutdown."""
    global _client_instance
    if _client_instance is not None:
        await _client_instance.aclose()
        _client_instance = None
