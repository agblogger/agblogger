"""Tests for credential encryption/decryption (Issue 5)."""

from __future__ import annotations

import pytest

from backend.exceptions import InternalServerError
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.services.key_derivation import derive_access_token_key, derive_encryption_key


class TestCryptoService:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        secret = "my-app-secret"
        plaintext = '{"username": "admin", "password": "secret123"}'
        ciphertext = encrypt_value(plaintext, secret)
        assert ciphertext != plaintext
        assert decrypt_value(ciphertext, secret) == plaintext

    def test_different_keys_produce_different_ciphertext(self) -> None:
        plaintext = "hello"
        ct1 = encrypt_value(plaintext, "key-one")
        ct2 = encrypt_value(plaintext, "key-two")
        assert ct1 != ct2

    def test_decrypt_with_wrong_key_raises(self) -> None:
        ciphertext = encrypt_value("secret data", "correct-key")
        with pytest.raises(InternalServerError, match="Failed to decrypt"):
            decrypt_value(ciphertext, "wrong-key")

    def test_decrypt_garbage_raises(self) -> None:
        with pytest.raises(InternalServerError, match="Failed to decrypt"):
            decrypt_value("not-valid-ciphertext", "any-key")

    def test_empty_string_roundtrip(self) -> None:
        secret = "key"
        ciphertext = encrypt_value("", secret)
        assert decrypt_value(ciphertext, secret) == ""

    def test_unicode_roundtrip(self) -> None:
        secret = "key"
        plaintext = "Héllo Wörld 🌍"
        ciphertext = encrypt_value(plaintext, secret)
        assert decrypt_value(ciphertext, secret) == plaintext

    def test_deterministic_key_derivation(self) -> None:
        """Same secret key always produces the same Fernet key (deterministic)."""
        ct1 = encrypt_value("test", "same-key")
        # Fernet adds random IV, so ciphertexts differ, but decryption works
        ct2 = encrypt_value("test", "same-key")
        assert ct1 != ct2  # random IV
        assert decrypt_value(ct1, "same-key") == "test"
        assert decrypt_value(ct2, "same-key") == "test"

    def test_encryption_key_is_separate_from_token_signing_key(self) -> None:
        secret = "same-key"
        assert derive_encryption_key(secret).decode("ascii") != derive_access_token_key(secret)
