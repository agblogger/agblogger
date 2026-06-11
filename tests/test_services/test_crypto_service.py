"""Tests for credential encryption/decryption (Issue 5)."""

from __future__ import annotations

import pytest

from backend.exceptions import InternalServerError
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.services.key_derivation import derive_access_token_key, derive_encryption_key

# ── Task 5: Ciphertext NewType ────────────────────────────────────────────────


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


class TestCiphertextNewType:
    def test_ciphertext_type_is_exported_from_crypto_service(self) -> None:
        """Ciphertext NewType must be importable from crypto_service."""
        from backend.services.crypto_service import Ciphertext

        # NewType is just str at runtime, so Ciphertext is callable and returns str
        assert callable(Ciphertext)

    def test_encrypt_value_return_is_str_instance(self) -> None:
        """encrypt_value returns an instance of str (Ciphertext is str at runtime)."""
        result = encrypt_value("plaintext", "secret")
        assert isinstance(result, str)

    def test_ciphertext_annotation_on_encrypt_value(self) -> None:
        """encrypt_value's return annotation should be Ciphertext."""
        import inspect

        from backend.services.crypto_service import Ciphertext

        hints = {}
        try:
            import typing

            hints = typing.get_type_hints(encrypt_value)
        except Exception:
            sig = inspect.signature(encrypt_value)
            ann = sig.return_annotation
            # If no annotation or annotation is inspect.Parameter.empty, fail
            assert ann is not inspect.Parameter.empty, (
                "encrypt_value has no return annotation; expected Ciphertext"
            )
            return
        return_hint = hints.get("return")
        assert return_hint is Ciphertext, (
            f"encrypt_value return annotation is {return_hint!r}, expected Ciphertext"
        )
