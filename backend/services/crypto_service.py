"""Symmetric encryption for credentials stored at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from backend.exceptions import InternalServerError
from backend.services.key_derivation import derive_encryption_key


def encrypt_value(plaintext: str, secret_key: str) -> str:
    """Encrypt a string and return the ciphertext as a URL-safe string."""
    f = Fernet(derive_encryption_key(secret_key))
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, secret_key: str) -> str:
    """Decrypt a ciphertext string. Raises ValueError on failure."""
    f = Fernet(derive_encryption_key(secret_key))
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise InternalServerError("Failed to decrypt credential data") from exc
