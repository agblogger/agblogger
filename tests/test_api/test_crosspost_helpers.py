"""Tests for crosspost API helper functions."""

from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi import HTTPException

from backend.api.crosspost import _generate_pkce_pair, _store_pending_oauth_state
from backend.crosspost.bluesky_oauth_state import OAuthStateStore


class TestGeneratePkcePair:
    """Tests for PKCE code verifier and challenge generation (RFC 7636)."""

    def test_verifier_length_is_64(self) -> None:
        verifier, _ = _generate_pkce_pair()
        assert len(verifier) == 64

    def test_verifier_uses_only_unreserved_characters(self) -> None:
        unreserved = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        verifier, _ = _generate_pkce_pair()
        assert set(verifier).issubset(unreserved)

    def test_challenge_is_base64url_sha256_of_verifier(self) -> None:
        verifier, challenge = _generate_pkce_pair()
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge

    def test_generates_unique_pairs(self) -> None:
        pairs = [_generate_pkce_pair() for _ in range(10)]
        verifiers = [v for v, _ in pairs]
        assert len(set(verifiers)) == 10

    def test_challenge_has_no_padding(self) -> None:
        _, challenge = _generate_pkce_pair()
        assert "=" not in challenge


class TestStorePendingOAuthState:
    """Tests for _store_pending_oauth_state exception-to-HTTP-status mapping."""

    def test_success_stores_state(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        _store_pending_oauth_state(store, "state-1", {"user_id": 1})
        assert store.get("state-1") == {"user_id": 1}

    def test_per_user_limit_raises_429(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=10, max_entries_per_user=1)
        store.set("state-1", {"user_id": 1})

        with pytest.raises(HTTPException) as exc_info:
            _store_pending_oauth_state(store, "state-2", {"user_id": 1})

        assert exc_info.value.status_code == 429
        assert "Too many pending OAuth flows" in exc_info.value.detail

    def test_global_capacity_raises_503(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=1, max_entries_per_user=5)
        store.set("state-1", {"user_id": 1})

        with pytest.raises(HTTPException) as exc_info:
            _store_pending_oauth_state(store, "state-2", {"user_id": 2})

        assert exc_info.value.status_code == 503
        assert "temporarily unavailable" in exc_info.value.detail
