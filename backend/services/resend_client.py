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


def _get_client() -> httpx.AsyncClient:
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


async def create_segment(*, api_key: str, name: str) -> str:
    """Create a segment/audience and return its id."""
    data = await _post(api_key, "/audiences", {"name": name})
    segment_id = str(data.get("id", ""))
    if not segment_id:
        raise ResendError("Resend did not return a segment id")
    return segment_id


async def create_and_send_broadcast(
    *, api_key: str, segment_id: str, from_: str, subject: str, html: str, text: str
) -> str:
    """Create a broadcast to the segment and send it now. Returns the broadcast id."""
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
    await _post(api_key, f"/broadcasts/{broadcast_id}/send", {})
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
