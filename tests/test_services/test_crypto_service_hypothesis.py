"""Property-based tests for symmetric encryption."""

from __future__ import annotations

import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.exceptions import InternalServerError
from backend.services.crypto_service import decrypt_value, encrypt_value

PROPERTY_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_PLAINTEXT = st.text(min_size=0, max_size=500)

_SECRET_KEY = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=8,
    max_size=64,
)


class TestEncryptDecryptRoundtripProperties:
    @PROPERTY_SETTINGS
    @given(plaintext=_PLAINTEXT, secret_key=_SECRET_KEY)
    def test_decrypt_reverses_encrypt(self, plaintext: str, secret_key: str) -> None:
        """decrypt_value(encrypt_value(plaintext, key), key) == plaintext."""
        ciphertext = encrypt_value(plaintext, secret_key)
        assert decrypt_value(ciphertext, secret_key) == plaintext

    @PROPERTY_SETTINGS
    @given(plaintext=_PLAINTEXT, secret_key=_SECRET_KEY)
    def test_ciphertext_differs_from_plaintext(self, plaintext: str, secret_key: str) -> None:
        """Ciphertext is never the same as plaintext (Fernet overhead)."""
        ciphertext = encrypt_value(plaintext, secret_key)
        assert ciphertext != plaintext

    @PROPERTY_SETTINGS
    @given(plaintext=_PLAINTEXT, secret_key=_SECRET_KEY)
    def test_ciphertext_is_nonempty_ascii(self, plaintext: str, secret_key: str) -> None:
        """Fernet ciphertext is non-empty URL-safe base64."""
        ciphertext = encrypt_value(plaintext, secret_key)
        assert len(ciphertext) > 0
        assert ciphertext.isascii()


class TestWrongKeyRejectionProperties:
    @PROPERTY_SETTINGS
    @given(plaintext=_PLAINTEXT, right_key=_SECRET_KEY, wrong_key=_SECRET_KEY)
    def test_wrong_key_raises_error(self, plaintext: str, right_key: str, wrong_key: str) -> None:
        """Decrypting with the wrong key raises InternalServerError."""
        if right_key == wrong_key:
            return
        ciphertext = encrypt_value(plaintext, right_key)
        with pytest.raises(InternalServerError):
            decrypt_value(ciphertext, wrong_key)


class TestKeyDerivationProperties:
    @PROPERTY_SETTINGS
    @given(plaintext=_PLAINTEXT, secret_key=_SECRET_KEY)
    def test_same_key_always_decrypts(self, plaintext: str, secret_key: str) -> None:
        """The same key can always decrypt what it encrypted, regardless of timing."""
        ct1 = encrypt_value(plaintext, secret_key)
        ct2 = encrypt_value(plaintext, secret_key)
        # Different ciphertexts (Fernet uses timestamps) but both decrypt correctly
        assert ct1 != ct2
        assert decrypt_value(ct1, secret_key) == plaintext
        assert decrypt_value(ct2, secret_key) == plaintext
