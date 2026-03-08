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


def require_str_field(
    data: dict[str, Any],
    field: str,
    *,
    context: str,
    error_cls: type[Exception] | None = None,
) -> str:
    """Extract a required non-empty string field from a dict.

    Raises *error_cls* (or ``ValueError`` when not given) if the field is
    missing, not a string, or empty.
    """
    value = data.get(field)
    if not isinstance(value, str) or not value:
        cls = error_cls or ValueError
        msg = f"{context} response missing {field}"
        raise cls(msg)
    return value


def get_str_field(data: dict[str, Any], field: str, default: str = "") -> str:
    """Extract an optional string field from a dict.

    Returns *default* if the field is missing or not a string.
    """
    value = data.get(field)
    return value if isinstance(value, str) else default
