"""Shared HTTP response utilities for cross-posting modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def parse_json_object(
    response: httpx.Response,
    *,
    error_cls: type[Exception] | None = None,
    context: str,
) -> dict[str, Any]:
    """Parse an HTTP response body as a JSON object (dict).

    Raises *error_cls* (or ``ValueError`` when not given) for non-JSON bodies
    (with a snippet of the response text) and for non-dict JSON values.
    """
    cls = error_cls or ValueError
    try:
        body = response.json()
    except ValueError as exc:
        snippet = response.text[:200] if response.text else "(empty)"
        msg = f"{context} returned non-JSON response: {snippet}"
        raise cls(msg) from exc
    if not isinstance(body, dict):
        msg = f"{context} returned non-object JSON"
        raise cls(msg)
    return cast("dict[str, Any]", body)
