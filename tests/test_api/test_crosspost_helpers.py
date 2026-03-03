"""Tests for crosspost API helper functions."""

from __future__ import annotations

import base64
import hashlib

from backend.api.crosspost import _generate_pkce_pair


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
