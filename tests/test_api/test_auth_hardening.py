"""Auth hardening integration tests."""

from __future__ import annotations

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
    (posts_dir / "hello.md").write_text("# Hello\n")
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
        auth_self_registration=False,
        auth_invites_enabled=True,
        auth_login_max_failures=2,
        auth_refresh_max_failures=2,
        auth_rate_limit_window_seconds=300,
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with initialized app state."""
    async with create_test_client(app_settings) as ac:
        yield ac


class TestRegistrationPolicy:
    @pytest.mark.asyncio
    async def test_register_requires_invite_when_self_registration_disabled(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "new@test.com",
                "password": "password1234",
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invite_code_allows_registration(self, client: AsyncClient) -> None:
        token_login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        assert token_login_resp.status_code == 200
        access_token = token_login_resp.json()["access_token"]

        invite_resp = await client.post(
            "/api/auth/invites",
            json={},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert invite_resp.status_code == 201
        invite_code = invite_resp.json()["invite_code"]
        session_login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert session_login_resp.status_code == 200
        csrf_token = session_login_resp.json()["csrf_token"]

        register_resp = await client.post(
            "/api/auth/register",
            json={
                "username": "invited-user",
                "email": "invited@test.com",
                "password": "password1234",
                "invite_code": invite_code,
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert register_resp.status_code == 201


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


class TestPersonalAccessTokens:
    @pytest.mark.asyncio
    async def test_pat_can_authenticate(self, client: AsyncClient) -> None:
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]

        pat_resp = await client.post(
            "/api/auth/pats",
            json={"name": "cli", "expires_days": 30},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert pat_resp.status_code == 201
        pat_token = pat_resp.json()["token"]

        me_resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {pat_token}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "admin"


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


class TestPATManagement:
    @pytest.mark.asyncio
    async def test_list_pats_returns_created_tokens(self, client: AsyncClient) -> None:
        """Create 2 PATs, list them, verify both appear with correct names."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        pat1_resp = await client.post(
            "/api/auth/pats",
            json={"name": "cli-token", "expires_days": 30},
            headers=headers,
        )
        assert pat1_resp.status_code == 201

        pat2_resp = await client.post(
            "/api/auth/pats",
            json={"name": "deploy-token", "expires_days": 60},
            headers=headers,
        )
        assert pat2_resp.status_code == 201

        list_resp = await client.get("/api/auth/pats", headers=headers)
        assert list_resp.status_code == 200
        data = list_resp.json()
        names = [pat["name"] for pat in data]
        assert "cli-token" in names
        assert "deploy-token" in names

    @pytest.mark.asyncio
    async def test_list_pats_requires_auth(self, client: AsyncClient) -> None:
        """GET /api/auth/pats without auth returns 401."""
        resp = await client.get("/api/auth/pats")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_revoke_pat_succeeds(self, client: AsyncClient) -> None:
        """Create PAT, revoke it, verify it no longer works for authentication."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        pat_resp = await client.post(
            "/api/auth/pats",
            json={"name": "revoke-test", "expires_days": 30},
            headers=headers,
        )
        assert pat_resp.status_code == 201
        pat_token = pat_resp.json()["token"]
        pat_id = pat_resp.json()["id"]

        # Verify the PAT works before revocation
        me_resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {pat_token}"},
        )
        assert me_resp.status_code == 200

        # Revoke the PAT
        revoke_resp = await client.delete(
            f"/api/auth/pats/{pat_id}",
            headers=headers,
        )
        assert revoke_resp.status_code == 204

        # Verify the PAT no longer works
        me_after = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {pat_token}"},
        )
        assert me_after.status_code == 401

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_pat_returns_404(self, client: AsyncClient) -> None:
        """DELETE /api/auth/pats/99999 returns 404."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await client.delete("/api/auth/pats/99999", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_pat_requires_auth(self, client: AsyncClient) -> None:
        """DELETE /api/auth/pats/{token_id} without auth returns 401."""
        resp = await client.delete("/api/auth/pats/1")
        assert resp.status_code == 401


class TestInviteCodeReuse:
    @pytest.mark.asyncio
    async def test_invite_code_reuse_rejected(self, client: AsyncClient) -> None:
        """Using the same invite code twice should be rejected."""
        login_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        session_login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        csrf_token = session_login_resp.json()["csrf_token"]

        # Create an invite
        invite_resp = await client.post(
            "/api/auth/invites",
            json={},
            headers=headers,
        )
        assert invite_resp.status_code == 201
        invite_code = invite_resp.json()["invite_code"]

        # Register first user with the invite
        reg1 = await client.post(
            "/api/auth/register",
            json={
                "username": "invite-user-1",
                "email": "invite1@test.com",
                "password": "password1234",
                "invite_code": invite_code,
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert reg1.status_code == 201

        # Attempt to register second user with the same invite code
        reg2 = await client.post(
            "/api/auth/register",
            json={
                "username": "invite-user-2",
                "email": "invite2@test.com",
                "password": "password1234",
                "invite_code": invite_code,
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert reg2.status_code == 403


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
    async def test_password_change_revokes_refresh_tokens_and_pats(
        self, client: AsyncClient
    ) -> None:
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

        pat_resp = await client.post(
            "/api/auth/pats",
            json={"name": "rotation-test", "expires_days": 30},
            headers=headers,
        )
        assert pat_resp.status_code == 201
        pat_token = pat_resp.json()["token"]

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

        pat_me_resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {pat_token}"},
        )
        assert pat_me_resp.status_code == 401


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
