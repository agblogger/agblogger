"""Context-separated key derivation for signing and encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac

_JWT_SIGNING_CONTEXT = b"agblogger:jwt-signing:v1"
_CREDENTIAL_ENCRYPTION_CONTEXT = b"agblogger:credential-encryption:v1"
_CSRF_TOKEN_CONTEXT = b"agblogger:csrf-token:v1"


def _derive(secret_key: str, context: bytes) -> bytes:
    return hmac.new(secret_key.encode("utf-8"), context, hashlib.sha256).digest()


def derive_access_token_key(secret_key: str) -> str:
    """Derive a signing key for access tokens from the application secret."""
    return base64.urlsafe_b64encode(_derive(secret_key, _JWT_SIGNING_CONTEXT)).decode("ascii")


def derive_encryption_key(secret_key: str) -> bytes:
    """Derive a Fernet-compatible encryption key from the application secret."""
    return base64.urlsafe_b64encode(_derive(secret_key, _CREDENTIAL_ENCRYPTION_CONTEXT))


def derive_csrf_token_key(secret_key: str) -> bytes:
    """Derive an HMAC key for stateless CSRF tokens."""
    return _derive(secret_key, _CSRF_TOKEN_CONTEXT)
