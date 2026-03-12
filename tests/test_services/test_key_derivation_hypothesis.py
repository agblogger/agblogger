"""Property-based tests for context-separated key derivation."""

from __future__ import annotations

import base64
import string

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from backend.services.key_derivation import (
    derive_access_token_key,
    derive_csrf_token_key,
    derive_encryption_key,
)

PROPERTY_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_SECRET_KEY = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=32,
    max_size=64,
)


class TestContextSeparationProperties:
    """For any secret key, the three derivation functions produce distinct keys."""

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_access_token_key_differs_from_encryption_key(self, secret_key: str) -> None:
        """derive_access_token_key(k) != derive_encryption_key(k) for all k."""
        access_key = derive_access_token_key(secret_key)
        encryption_key = derive_encryption_key(secret_key)
        # Compare the underlying derived bytes (before encoding differences)
        access_bytes = base64.urlsafe_b64decode(access_key)
        encryption_bytes = base64.urlsafe_b64decode(encryption_key)
        assert access_bytes != encryption_bytes

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_access_token_key_differs_from_csrf_key(self, secret_key: str) -> None:
        """derive_access_token_key(k) != derive_csrf_token_key(k) for all k."""
        access_key = derive_access_token_key(secret_key)
        csrf_key = derive_csrf_token_key(secret_key)
        access_bytes = base64.urlsafe_b64decode(access_key)
        assert access_bytes != csrf_key

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_encryption_key_differs_from_csrf_key(self, secret_key: str) -> None:
        """derive_encryption_key(k) != derive_csrf_token_key(k) for all k."""
        encryption_key = derive_encryption_key(secret_key)
        csrf_key = derive_csrf_token_key(secret_key)
        encryption_bytes = base64.urlsafe_b64decode(encryption_key)
        assert encryption_bytes != csrf_key

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_all_three_keys_mutually_distinct(self, secret_key: str) -> None:
        """All three derived keys are pairwise distinct for any secret."""
        access_bytes = base64.urlsafe_b64decode(derive_access_token_key(secret_key))
        encryption_bytes = base64.urlsafe_b64decode(derive_encryption_key(secret_key))
        csrf_bytes = derive_csrf_token_key(secret_key)
        assert len({access_bytes, encryption_bytes, csrf_bytes}) == 3


class TestDeterminismProperties:
    """Same input always produces the same output."""

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_access_token_key_is_deterministic(self, secret_key: str) -> None:
        """derive_access_token_key(k) == derive_access_token_key(k)."""
        assert derive_access_token_key(secret_key) == derive_access_token_key(secret_key)

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_encryption_key_is_deterministic(self, secret_key: str) -> None:
        """derive_encryption_key(k) == derive_encryption_key(k)."""
        assert derive_encryption_key(secret_key) == derive_encryption_key(secret_key)

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_csrf_token_key_is_deterministic(self, secret_key: str) -> None:
        """derive_csrf_token_key(k) == derive_csrf_token_key(k)."""
        assert derive_csrf_token_key(secret_key) == derive_csrf_token_key(secret_key)


class TestDistinctInputsProperties:
    """Different secret keys produce different derived keys."""

    @PROPERTY_SETTINGS
    @given(key_a=_SECRET_KEY, key_b=_SECRET_KEY)
    def test_different_secrets_produce_different_access_token_keys(
        self, key_a: str, key_b: str
    ) -> None:
        """k1 != k2 implies derive_access_token_key(k1) != derive_access_token_key(k2)."""
        assume(key_a != key_b)
        assert derive_access_token_key(key_a) != derive_access_token_key(key_b)

    @PROPERTY_SETTINGS
    @given(key_a=_SECRET_KEY, key_b=_SECRET_KEY)
    def test_different_secrets_produce_different_encryption_keys(
        self, key_a: str, key_b: str
    ) -> None:
        """k1 != k2 implies derive_encryption_key(k1) != derive_encryption_key(k2)."""
        assume(key_a != key_b)
        assert derive_encryption_key(key_a) != derive_encryption_key(key_b)

    @PROPERTY_SETTINGS
    @given(key_a=_SECRET_KEY, key_b=_SECRET_KEY)
    def test_different_secrets_produce_different_csrf_keys(self, key_a: str, key_b: str) -> None:
        """k1 != k2 implies derive_csrf_token_key(k1) != derive_csrf_token_key(k2)."""
        assume(key_a != key_b)
        assert derive_csrf_token_key(key_a) != derive_csrf_token_key(key_b)


class TestOutputFormatProperties:
    """Derived keys have the correct format and length for their purpose."""

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_access_token_key_is_nonempty_ascii_string(self, secret_key: str) -> None:
        """Access token key is a non-empty ASCII string."""
        key = derive_access_token_key(secret_key)
        assert isinstance(key, str)
        assert len(key) > 0
        assert key.isascii()

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_access_token_key_is_base64_decodable(self, secret_key: str) -> None:
        """Access token key is valid URL-safe base64 encoding of 32 bytes."""
        key = derive_access_token_key(secret_key)
        raw = base64.urlsafe_b64decode(key)
        assert len(raw) == 32

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_encryption_key_is_nonempty_bytes(self, secret_key: str) -> None:
        """Encryption key is non-empty bytes."""
        key = derive_encryption_key(secret_key)
        assert isinstance(key, bytes)
        assert len(key) > 0

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_encryption_key_is_base64_decodable(self, secret_key: str) -> None:
        """Encryption key is valid URL-safe base64 encoding of 32 bytes."""
        key = derive_encryption_key(secret_key)
        raw = base64.urlsafe_b64decode(key)
        assert len(raw) == 32

    @PROPERTY_SETTINGS
    @given(secret_key=_SECRET_KEY)
    def test_csrf_key_is_32_raw_bytes(self, secret_key: str) -> None:
        """CSRF token key is raw 32-byte HMAC-SHA256 digest."""
        key = derive_csrf_token_key(secret_key)
        assert isinstance(key, bytes)
        assert len(key) == 32
