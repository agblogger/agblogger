"""Signed, expiring subscribe-confirmation tokens (no server-side storage)."""

from __future__ import annotations

from datetime import timedelta

import jwt

from backend.services.key_derivation import derive_subscribe_confirm_key
from backend.utils.datetime import now_utc

_ALGORITHM = "HS256"
_CONFIRM_TYPE_CLAIM = "subscribe-confirm"
_DEFAULT_EXPIRES_MINUTES = 60 * 48  # 48h confirmation window


def normalize_email(email: str) -> str:
    """Trim + lowercase for consistent dedup and token payloads."""
    return email.strip().lower()


def create_confirm_token(
    email: str, secret_key: str, *, expires_minutes: int = _DEFAULT_EXPIRES_MINUTES
) -> str:
    """Create a signed token carrying the (normalized) email and an expiry."""
    payload = {
        "email": normalize_email(email),
        "type": _CONFIRM_TYPE_CLAIM,
        "exp": now_utc() + timedelta(minutes=expires_minutes),
    }
    return str(jwt.encode(payload, derive_subscribe_confirm_key(secret_key), algorithm=_ALGORITHM))


def verify_confirm_token(token: str, secret_key: str) -> str | None:
    """Return the normalized email if the token is valid and unexpired, else None."""
    try:
        payload = jwt.decode(
            token, derive_subscribe_confirm_key(secret_key), algorithms=[_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != _CONFIRM_TYPE_CLAIM:
        return None
    email = payload.get("email")
    return email if isinstance(email, str) and email else None
