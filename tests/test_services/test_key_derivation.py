"""Tests for context-separated key derivation."""

from __future__ import annotations

from backend.services.key_derivation import (
    derive_access_token_key,
    derive_csrf_token_key,
    derive_encryption_key,
)


class TestDeriveCsrfTokenKey:
    def test_returns_32_bytes(self) -> None:
        key = derive_csrf_token_key("test-secret-key")
        assert isinstance(key, bytes)
        assert len(key) == 32


class TestContextSeparation:
    def test_all_three_derive_functions_produce_different_keys(self) -> None:
        secret = "shared-secret-key-for-all-three"
        access_key = derive_access_token_key(secret)
        encryption_key = derive_encryption_key(secret)
        csrf_key = derive_csrf_token_key(secret)

        # access_key is a base64 str, encryption_key is base64 bytes, csrf_key is raw bytes
        # Convert all to bytes for comparison
        access_bytes = access_key.encode("ascii")
        encryption_bytes = encryption_key

        assert access_bytes != encryption_bytes
        assert access_bytes != csrf_key
        assert encryption_bytes != csrf_key


class TestDeterminism:
    def test_same_input_produces_same_output(self) -> None:
        secret = "deterministic-test-secret"
        assert derive_access_token_key(secret) == derive_access_token_key(secret)
        assert derive_encryption_key(secret) == derive_encryption_key(secret)
        assert derive_csrf_token_key(secret) == derive_csrf_token_key(secret)
