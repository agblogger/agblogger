"""Tests for CSRF token service."""

from __future__ import annotations

from backend.services.csrf_service import create_csrf_token, validate_csrf_token


class TestCreateCsrfToken:
    def test_produces_non_empty_base64_string(self) -> None:
        token = create_csrf_token("access-token-123", "my-secret-key-at-least-32-chars!")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_different_access_tokens_produce_different_csrf_tokens(self) -> None:
        secret = "shared-secret-key-at-least-32-chars!"
        token_a = create_csrf_token("access-token-A", secret)
        token_b = create_csrf_token("access-token-B", secret)
        assert token_a != token_b

    def test_different_secret_keys_produce_different_csrf_tokens(self) -> None:
        access = "same-access-token"
        token_a = create_csrf_token(access, "secret-key-alpha-long-enough-1234")
        token_b = create_csrf_token(access, "secret-key-bravo-long-enough-1234")
        assert token_a != token_b


class TestValidateCsrfToken:
    def test_returns_true_for_correct_token(self) -> None:
        secret = "my-secret-key-at-least-32-chars!"
        access = "access-token-123"
        token = create_csrf_token(access, secret)
        assert validate_csrf_token(access, token, secret) is True

    def test_returns_false_for_tampered_token(self) -> None:
        secret = "my-secret-key-at-least-32-chars!"
        access = "access-token-123"
        token = create_csrf_token(access, secret)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert validate_csrf_token(access, tampered, secret) is False

    def test_returns_false_for_empty_token(self) -> None:
        secret = "my-secret-key-at-least-32-chars!"
        access = "access-token-123"
        assert validate_csrf_token(access, "", secret) is False
