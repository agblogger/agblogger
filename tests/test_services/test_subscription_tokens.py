"""Stateless subscribe-confirm tokens: round-trip, tamper, expiry, type."""

from __future__ import annotations

import jwt

from backend.services.key_derivation import derive_subscribe_confirm_key
from backend.services.subscription_tokens import (
    create_confirm_token,
    verify_confirm_token,
)

SECRET = "x" * 48


def test_round_trip() -> None:
    token = create_confirm_token("Reader@Example.com ", SECRET)
    # Email is normalized inside the token payload.
    assert verify_confirm_token(token, SECRET) == "reader@example.com"


def test_tampered_token_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET)
    assert verify_confirm_token(token + "x", SECRET) is None


def test_wrong_secret_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET)
    assert verify_confirm_token(token, "y" * 48) is None


def test_expired_token_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET, expires_minutes=-1)
    assert verify_confirm_token(token, SECRET) is None


def test_wrong_type_claim_rejected() -> None:
    key = derive_subscribe_confirm_key(SECRET)
    token = jwt.encode({"email": "a@b.com", "type": "other"}, key, algorithm="HS256")
    assert verify_confirm_token(token, SECRET) is None


def test_missing_type_claim_rejected() -> None:
    key = derive_subscribe_confirm_key(SECRET)
    token = jwt.encode({"email": "a@b.com"}, key, algorithm="HS256")
    assert verify_confirm_token(token, SECRET) is None
