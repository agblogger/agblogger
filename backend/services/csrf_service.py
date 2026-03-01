"""Stateless CSRF token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from backend.services.key_derivation import derive_csrf_token_key


def create_csrf_token(access_token: str, secret_key: str) -> str:
    """Create a stateless CSRF token bound to the current access token."""
    csrf_key = derive_csrf_token_key(secret_key)
    digest = hmac.new(csrf_key, access_token.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def validate_csrf_token(access_token: str, csrf_token: str, secret_key: str) -> bool:
    """Validate a stateless CSRF token against the current access token."""
    expected = create_csrf_token(access_token, secret_key)
    return secrets.compare_digest(expected, csrf_token)
