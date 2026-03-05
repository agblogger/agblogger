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

    If *error_cls* is provided, non-JSON and non-dict responses raise that
    exception type.  Otherwise the raw ``ValueError`` propagates for non-JSON
    bodies, and a plain ``ValueError`` is raised for non-dict JSON values.
    """
    try:
        body = response.json()
    except ValueError as exc:
        if error_cls is None:
            raise
        msg = f"{context} returned non-JSON response"
        raise error_cls(msg) from exc
    if not isinstance(body, dict):
        if error_cls is None:
            raise ValueError(f"{context} returned non-object JSON")
        msg = f"{context} returned invalid JSON object"
        raise error_cls(msg)
    return cast("dict[str, Any]", body)
