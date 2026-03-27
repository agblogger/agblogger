"""Auth hardening integration tests."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create hardened auth settings for tests."""
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text("# Hello\n")
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        auth_login_max_failures=2,
        auth_refresh_max_failures=2,
        auth_rate_limit_window_seconds=300,
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with initialized app state."""
    async with create_test_client(app_settings) as ac:
        yield ac


class TestCsrf:
    @pytest.mark.asyncio
    async def test_login_returns_csrf_token_without_csrf_cookie_or_response_header(
        self, client: AsyncClient
    ) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200

        assert login_resp.json()["csrf_token"]
        assert login_resp.headers.get("X-CSRF-Token") is None

        set_cookie_values = login_resp.headers.get_list("set-cookie")
        assert all(not value.startswith("csrf_token=") for value in set_cookie_values)

    @pytest.mark.asyncio
    async def test_authenticated_get_does_not_echo_csrf_token_header(
        self, client: AsyncClient
    ) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200

        me_resp = await client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.headers.get("X-CSRF-Token") is None

    @pytest.mark.asyncio
    async def test_csrf_endpoint_returns_token_for_cookie_session(
        self, client: AsyncClient
    ) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200

        csrf_resp = await client.get("/api/auth/csrf")
        assert csrf_resp.status_code == 200
        assert csrf_resp.json()["csrf_token"] == login_resp.json()["csrf_token"]
        assert csrf_resp.headers.get("X-CSRF-Token") is None
        assert all(
            not value.startswith("csrf_token=")
            for value in csrf_resp.headers.get_list("set-cookie")
        )

    @pytest.mark.asyncio
    async def test_session_login_response_omits_bearer_tokens(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["csrf_token"]

    @pytest.mark.asyncio
    async def test_token_login_returns_access_token_without_setting_cookies(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        assert token_resp.status_code == 200
        data = token_resp.json()
        assert data["access_token"]
        assert data["token_type"] == "bearer"
        set_cookie_values = token_resp.headers.get_list("set-cookie")
        assert set_cookie_values == []

    @pytest.mark.asyncio
    async def test_token_login_rejects_browser_originated_requests(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
            headers={"Origin": "http://testserver"},
        )
        assert token_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_session_refresh_response_omits_bearer_tokens(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        csrf_token = login_resp.json()["csrf_token"]

        refresh_resp = await client.post(
            "/api/auth/refresh",
            json={},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["csrf_token"]

    @pytest.mark.asyncio
    async def test_csrf_endpoint_returns_401_when_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/auth/csrf")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_authenticated_post_requires_csrf(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200

        without_csrf = await client.post(
            "/api/render/preview",
            json={"markdown": "# Hello"},
        )
        assert without_csrf.status_code == 403

        csrf_token = login_resp.json()["csrf_token"]

        with_csrf = await client.post(
            "/api/render/preview",
            json={"markdown": "# Hello"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert with_csrf.status_code == 200


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_login_failed_attempts_rate_limited(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        second = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert first.status_code == 401
        assert second.status_code == 429

    @pytest.mark.asyncio
    async def test_refresh_failed_attempts_rate_limited(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "bad-token"},
        )
        second = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "bad-token"},
        )
        assert first.status_code == 401
        assert second.status_code == 429


class TestPasswordModelValidation:
    @pytest.mark.asyncio
    async def test_mismatched_passwords_returns_422(self, client: AsyncClient) -> None:
        """Mismatched new_password and confirm_password returns 422 from model_validator."""
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword1234",
                "confirm_password": "differentpassword",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 422


class TestPasswordRateLimiting:
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_password_change_rate_limited_after_failures(self, client: AsyncClient) -> None:
        """Exceeding the failure threshold should trigger 429."""
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        wrong_body = {
            "current_password": "wrong-password",
            "new_password": "newpassword1234",
            "confirm_password": "newpassword1234",
        }

        # Send 5 wrong-password attempts (the configured threshold)
        for _ in range(5):
            resp = await client.put("/api/admin/password", json=wrong_body, headers=headers)
            assert resp.status_code == 400

        # The 6th attempt should be rate-limited
        limited = await client.put("/api/admin/password", json=wrong_body, headers=headers)
        assert limited.status_code == 429


class TestPasswordChangeSessionRevocation:
    @pytest.mark.asyncio
    async def test_password_change_response_includes_sessions_revoked(
        self, client: AsyncClient
    ) -> None:
        """Password change response should include sessions_revoked: true."""
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword1234",
                "confirm_password": "newpassword1234",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions_revoked"] is True


class TestTokenLoginRefererHeader:
    @pytest.mark.asyncio
    async def test_token_login_rejects_referer_header(self, client: AsyncClient) -> None:
        """Token-login should reject requests with Referer header (browser-originated)."""
        resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
            headers={"Referer": "http://evil.com/page"},
        )
        assert resp.status_code == 403


class TestPasswordRotation:
    @pytest.mark.asyncio
    async def test_password_change_revokes_refresh_tokens(self, client: AsyncClient) -> None:
        session_login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert session_login_resp.status_code == 200
        csrf_token = session_login_resp.json()["csrf_token"]

        token_login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        assert token_login_resp.status_code == 200
        access_token = token_login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        change_resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "admin-password-456",
                "confirm_password": "admin-password-456",
            },
            headers=headers,
        )
        assert change_resp.status_code == 200

        refresh_resp = await client.post(
            "/api/auth/refresh",
            json={},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert refresh_resp.status_code == 401


class TestLoginErrorMessage:
    @pytest.mark.asyncio
    async def test_wrong_password_returns_generic_credentials_error(
        self, client: AsyncClient
    ) -> None:
        """Login failure must not reveal whether the username or password was wrong."""
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert "username" not in detail.lower()
        assert "password" not in detail.lower()
        assert detail == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_wrong_username_returns_generic_credentials_error(
        self, client: AsyncClient
    ) -> None:
        """Login failure for nonexistent user must not reveal the user doesn't exist."""
        resp = await client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "admin123"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert "username" not in detail.lower()
        assert "password" not in detail.lower()
        assert detail == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_token_login_wrong_password_returns_generic_credentials_error(
        self, client: AsyncClient
    ) -> None:
        """Token-login failure must use the same generic error message."""
        resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"


class TestTokenLoginRateLimiting:
    @pytest.mark.asyncio
    async def test_token_login_rate_limited_after_max_failures(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "wrong"},
        )
        second = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "wrong"},
        )
        assert first.status_code == 401
        assert second.status_code == 429


class TestCsrfTamperedToken:
    @pytest.mark.asyncio
    async def test_tampered_csrf_token_rejected(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        csrf_token = login_resp.json()["csrf_token"]

        # Tamper with the CSRF token
        tampered = csrf_token[:-1] + ("A" if csrf_token[-1] != "A" else "B")
        resp = await client.post(
            "/api/render/preview",
            json={"markdown": "# Test"},
            headers={"X-CSRF-Token": tampered},
        )
        assert resp.status_code == 403


class TestOldPasswordAfterChange:
    @pytest.mark.asyncio
    async def test_old_password_stops_working_after_change(self, client: AsyncClient) -> None:
        """After changing password, the old password should no longer work."""
        # Login with original password
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Change the password
        change_resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword456",
                "confirm_password": "newpassword456",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert change_resp.status_code == 200

        # Attempt login with old password
        old_login = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert old_login.status_code == 401

        # Verify new password works
        new_login = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "newpassword456"},
        )
        assert new_login.status_code == 200


class TestGetCurrentAdminLogging:
    """get_current_admin must log differentiated messages for different auth failure modes.

    Logging is handled by decode_access_token in the auth service layer — the deps
    layer must NOT duplicate these log entries with a redundant pre-decode.
    """

    @pytest.mark.asyncio
    async def test_expired_token_logs_debug_exactly_once(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An expired access token should produce exactly one DEBUG log about expiry."""
        from backend.services.auth_service import create_access_token

        expired_token = create_access_token(
            {"sub": "1", "username": "admin"},
            "test-secret-key-with-at-least-32-characters",
            expires_minutes=-1,
        )
        with caplog.at_level(logging.DEBUG):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {expired_token}"},
            )
        assert resp.status_code == 401
        debug_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "expired" in r.message.lower()
        ]
        assert len(debug_records) == 1

    @pytest.mark.asyncio
    async def test_invalid_token_logs_warning_exactly_once(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed/invalid access token should produce exactly one WARNING log."""
        with caplog.at_level(logging.DEBUG):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer not-a-valid-jwt-token"},
            )
        assert resp.status_code == 401
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "invalid" in r.message.lower()
        ]
        assert len(warning_records) == 1

    @pytest.mark.asyncio
    async def test_token_with_missing_sub_logs_warning(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A token without a sub claim should produce a WARNING log."""
        from datetime import timedelta

        import jwt as pyjwt

        from backend.services.auth_service import ALGORITHM
        from backend.services.key_derivation import derive_access_token_key
        from backend.utils.datetime import now_utc

        secret = "test-secret-key-with-at-least-32-characters"
        signing_key = derive_access_token_key(secret)
        exp = now_utc() + timedelta(minutes=15)
        token = pyjwt.encode(
            {"username": "admin", "type": "access", "exp": exp},
            signing_key,
            algorithm=ALGORITHM,
        )
        with caplog.at_level(logging.DEBUG, logger="backend.api.deps"):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 401
        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING and "sub" in r.message.lower()
        ]
        assert len(warning_records) >= 1

    @pytest.mark.asyncio
    async def test_token_with_nonexistent_user_logs_warning(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A token referencing a non-existent user id should produce a WARNING log."""
        from backend.services.auth_service import create_access_token

        token = create_access_token(
            {"sub": "99999", "username": "ghost"},
            "test-secret-key-with-at-least-32-characters",
        )
        with caplog.at_level(logging.DEBUG, logger="backend.api.deps"):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 401
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "non-existent" in r.message.lower()
        ]
        assert len(warning_records) >= 1
        assert all("99999" not in record.message for record in warning_records)

    @pytest.mark.asyncio
    async def test_token_with_invalid_sub_type_logs_without_raw_claim_details(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid sub claim warnings must not leak raw claim metadata."""
        from backend.services.auth_service import create_access_token

        token = create_access_token(
            {"sub": "not-a-number", "username": "admin"},
            "test-secret-key-with-at-least-32-characters",
        )
        with caplog.at_level(logging.DEBUG, logger="backend.api.deps"):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "invalid sub claim" in r.message.lower()
        ]
        assert len(warning_records) >= 1
        assert all("str" not in record.message.lower() for record in warning_records)
