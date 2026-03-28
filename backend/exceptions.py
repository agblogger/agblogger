"""Application-level exception types.

Convention:
- ``InternalServerError`` — for errors whose details must never reach clients
  (decryption failures, config validation, infrastructure port conflicts, etc.).
  The global handler logs the full message at ERROR and returns a generic
  "Internal server error" (500) to the client.
- ``ValueError`` — for *business logic* validation errors that are safe to
  forward to clients (invalid dates, bad input formats, etc.).  The global
  ``ValueError`` handler returns ``str(exc)`` as the 422 detail.
"""

from __future__ import annotations


class InternalServerError(Exception):
    """Raised for internal errors whose details must not be exposed to clients.

    The global exception handler in ``backend/main.py`` catches this, logs
    the full message server-side, and returns HTTP 500 with a generic
    ``"Internal server error"`` detail.
    """


class PostNotFoundError(ValueError):
    """Raised when a post is not found by path or ID."""


class BuiltinPageError(ValueError):
    """Raised when attempting to modify a built-in page (timeline, labels)."""


class CrossPostValidationError(ValueError):
    """Raised when a cross-posting request violates a business rule.

    Examples: attempting to cross-post a draft post, missing required fields.
    Inherits from ``ValueError`` so existing broad ``ValueError`` handlers
    remain compatible while the API can now catch this specific type.
    """


class ExternalServiceError(RuntimeError):
    """Raised when an external service (OAuth, HTTP API) fails.

    The global handler logs the full message at ERROR and returns a generic
    "External service error" (502) to the client.
    """
