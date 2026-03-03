"""Tests for cross-posting OAuth API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import create_test_client

pytestmark = pytest.mark.slow

if TYPE_CHECKING:
    from backend.config import Settings


class TestMastodonAuthorize:
    async def test_mastodon_authorize_requires_auth(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        async with create_test_client(test_settings) as client:
            resp = await client.post(
                "/api/crosspost/mastodon/authorize",
                json={"instance_url": "https://mastodon.social"},
            )
            assert resp.status_code == 401

    async def test_mastodon_authorize_rejects_invalid_instance(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]

            resp = await client.post(
                "/api/crosspost/mastodon/authorize",
                json={"instance_url": "http://localhost"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Invalid instance URL"

    async def test_mastodon_authorize_returns_503_when_not_configured(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = ""
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]

            resp = await client.post(
                "/api/crosspost/mastodon/authorize",
                json={"instance_url": "https://mastodon.social"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503


class TestMastodonCallback:
    async def test_mastodon_callback_rejects_invalid_state(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/mastodon/callback",
                params={"code": "test-code", "state": "invalid-state"},
                follow_redirects=False,
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Invalid or expired OAuth state"

    async def test_mastodon_callback_rejects_empty_acct(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            # Seed a valid pending OAuth state
            transport = client._transport
            state_store = transport.app.state.mastodon_oauth_state  # type: ignore[attr-defined]
            state_store.set(
                "test-state",
                {
                    "instance_url": "https://mastodon.social",
                    "client_id": "cid",
                    "client_secret": "csec",
                    "redirect_uri": "https://myblog.example.com/api/crosspost/mastodon/callback",
                    "pkce_verifier": "verifier",
                    "user_id": 1,
                },
            )

            mock_result: dict[str, str] = {
                "access_token": "valid-token",
                "acct": "",
                "hostname": "mastodon.social",
                "instance_url": "https://mastodon.social",
            }
            with patch(
                "backend.crosspost.mastodon.exchange_mastodon_oauth_token",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                resp = await client.get(
                    "/api/crosspost/mastodon/callback",
                    params={"code": "test-code", "state": "test-state"},
                    follow_redirects=False,
                )
            assert resp.status_code == 502
            assert "incomplete account info" in resp.json()["detail"]

    async def test_mastodon_callback_rejects_empty_hostname(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            # Seed a valid pending OAuth state
            transport = client._transport
            state_store = transport.app.state.mastodon_oauth_state  # type: ignore[attr-defined]
            state_store.set(
                "test-state",
                {
                    "instance_url": "https://mastodon.social",
                    "client_id": "cid",
                    "client_secret": "csec",
                    "redirect_uri": "https://myblog.example.com/api/crosspost/mastodon/callback",
                    "pkce_verifier": "verifier",
                    "user_id": 1,
                },
            )

            mock_result: dict[str, str] = {
                "access_token": "valid-token",
                "acct": "user",
                "hostname": "",
                "instance_url": "https://mastodon.social",
            }
            with patch(
                "backend.crosspost.mastodon.exchange_mastodon_oauth_token",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                resp = await client.get(
                    "/api/crosspost/mastodon/callback",
                    params={"code": "test-code", "state": "test-state"},
                    follow_redirects=False,
                )
            assert resp.status_code == 502
            assert "incomplete account info" in resp.json()["detail"]


class TestBlueskyCallbackTokenValidation:
    async def test_bluesky_callback_missing_access_token_returns_502(
        self, test_settings: Settings
    ) -> None:
        from unittest.mock import MagicMock

        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            transport = client._transport
            app = transport.app  # type: ignore[attr-defined]
            state_store = app.state.bluesky_oauth_state
            state_store.set(
                "test-state",
                {
                    "did": "did:plc:abc123",
                    "handle": "user.bsky.social",
                    "auth_server_meta": {
                        "issuer": "https://bsky.social",
                        "token_endpoint": "https://bsky.social/oauth/token",
                        "pds_url": "https://pds.bsky.social",
                    },
                    "dpop_nonce": "nonce",
                    "pkce_verifier": "verifier",
                    "user_id": 1,
                },
            )
            # Set the DPoP key/JWK on app state (normally set during startup)
            mock_key = MagicMock()
            mock_key.private_bytes.return_value = b"fake-pem"
            app.state.atproto_oauth_key = mock_key
            app.state.atproto_oauth_jwk = {"kty": "EC"}

            # Mock token exchange to return data missing access_token
            mock_token_data = {
                "sub": "did:plc:abc123",
                "refresh_token": "rt",
                "dpop_nonce": "new-nonce",
            }
            with patch(
                "backend.crosspost.atproto_oauth.exchange_code_for_tokens",
                new_callable=AsyncMock,
                return_value=mock_token_data,
            ):
                resp = await client.get(
                    "/api/crosspost/bluesky/callback",
                    params={
                        "code": "test-code",
                        "state": "test-state",
                        "iss": "https://bsky.social",
                    },
                    follow_redirects=False,
                )
            assert resp.status_code == 502
            assert "access_token" in resp.json()["detail"].lower()


class TestXAuthorize:
    async def test_x_authorize_requires_auth(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.post("/api/crosspost/x/authorize")
            assert resp.status_code == 401

    async def test_x_authorize_returns_503_when_not_configured(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = ""
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/x/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503

    async def test_x_authorize_returns_authorization_url(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/x/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "authorization_url" in data
            auth_url = data["authorization_url"]
            assert auth_url.startswith("https://x.com/i/oauth2/authorize?")
            assert "client_id=test_client_id" in auth_url
            assert "code_challenge_method=S256" in auth_url
            assert "response_type=code" in auth_url
            assert "scope=tweet.read+tweet.write+users.read+offline.access" in auth_url

    async def test_x_authorize_returns_503_when_bluesky_client_url_not_set(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = ""
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/x/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503


class TestXCallback:
    async def test_x_callback_rejects_invalid_state(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/x/callback",
                params={"code": "test-code", "state": "invalid-state"},
                follow_redirects=False,
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Invalid or expired OAuth state"

    async def test_x_callback_handles_oauth_error_from_provider(
        self, test_settings: Settings
    ) -> None:
        """Issue #2: When user denies access, X redirects with error param instead of code."""
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/x/callback",
                params={
                    "error": "access_denied",
                    "state": "some-state",
                },
                follow_redirects=False,
            )
            # Should redirect to admin with error, not 422 validation error
            assert resp.status_code == 303
            location = resp.headers.get("location", "")
            assert "/admin" in location
            assert "oauth_error" in location


class TestXCallbackTokenValidation:
    async def test_x_callback_missing_token_fields_returns_502(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.x_client_id = "test_client_id"
        test_settings.x_client_secret = "test_client_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            transport = client._transport
            state_store = transport.app.state.x_oauth_state  # type: ignore[attr-defined]
            state_store.set(
                "test-state",
                {
                    "client_id": "test_client_id",
                    "client_secret": "test_client_secret",
                    "redirect_uri": "https://myblog.example.com/api/crosspost/x/callback",
                    "pkce_verifier": "verifier",
                    "user_id": 1,
                },
            )

            # Mock token exchange to return incomplete data (missing username)
            mock_token_result = {
                "access_token": "at",
                "refresh_token": "rt",
                # username missing
            }
            with patch(
                "backend.crosspost.x.exchange_x_oauth_token",
                new_callable=AsyncMock,
                return_value=mock_token_result,
            ):
                resp = await client.get(
                    "/api/crosspost/x/callback",
                    params={"code": "test-code", "state": "test-state"},
                    follow_redirects=False,
                )
            assert resp.status_code == 502
            assert "incomplete" in resp.json()["detail"].lower()


class TestFacebookAuthorize:
    async def test_facebook_authorize_requires_auth(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.post("/api/crosspost/facebook/authorize")
            assert resp.status_code == 401

    async def test_facebook_authorize_returns_503_when_not_configured(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = ""
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/facebook/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503

    async def test_facebook_authorize_returns_503_when_bluesky_client_url_not_set(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = ""
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/facebook/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503

    async def test_facebook_authorize_returns_authorization_url(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/facebook/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "authorization_url" in data
            auth_url = data["authorization_url"]
            assert auth_url.startswith("https://www.facebook.com/v22.0/dialog/oauth?")
            assert "client_id=test_app_id" in auth_url
            assert "response_type=code" in auth_url
            assert "pages_manage_posts" in auth_url


class TestFacebookCallback:
    async def test_facebook_callback_rejects_invalid_state(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={"code": "test-code", "state": "invalid-state"},
                follow_redirects=False,
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Invalid or expired OAuth state"

    async def test_facebook_callback_handles_oauth_error_from_provider(
        self, test_settings: Settings
    ) -> None:
        """Issue #2: When user denies access, Facebook redirects with error param."""
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={
                    "error": "access_denied",
                    "error_reason": "user_denied",
                    "state": "some-state",
                },
                follow_redirects=False,
            )
            # Should redirect to admin with error, not 422
            assert resp.status_code == 303
            location = resp.headers.get("location", "")
            assert "/admin" in location
            assert "oauth_error" in location


class TestFacebookPages:
    async def test_facebook_pages_requires_auth(self, test_settings: Settings) -> None:
        """Issue #1: Facebook pages endpoint should require auth."""
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/facebook/pages",
                params={"state": "some-state"},
            )
            assert resp.status_code == 401

    async def test_facebook_pages_rejects_invalid_state(self, test_settings: Settings) -> None:
        """Issue #1: Invalid state token should return 400."""
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.get(
                "/api/crosspost/facebook/pages",
                params={"state": "invalid-state"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400


class TestFacebookSelectPage:
    async def test_facebook_select_page_requires_auth(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        async with create_test_client(test_settings) as client:
            resp = await client.post(
                "/api/crosspost/facebook/select-page",
                json={"state": "some-state", "page_id": "123"},
            )
            assert resp.status_code == 401

    async def test_facebook_select_page_rejects_invalid_state(
        self, test_settings: Settings
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        test_settings.facebook_app_id = "test_app_id"
        test_settings.facebook_app_secret = "test_app_secret"
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            resp = await client.post(
                "/api/crosspost/facebook/select-page",
                json={"state": "invalid-state", "page_id": "123"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Invalid or expired page selection state"


class TestDeleteSocialAccount:
    async def test_delete_requires_auth(self, test_settings: Settings) -> None:
        async with create_test_client(test_settings) as client:
            resp = await client.delete("/api/crosspost/accounts/999")
            assert resp.status_code == 401

    async def test_delete_nonexistent_returns_404(self, test_settings: Settings) -> None:
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]

            resp = await client.delete(
                "/api/crosspost/accounts/99999",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 404

    async def test_delete_succeeds(self, test_settings: Settings) -> None:
        test_settings.admin_password = "admin"
        async with create_test_client(test_settings) as client:
            login_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin"},
            )
            token = login_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Create a social account via the API
            create_resp = await client.post(
                "/api/crosspost/accounts",
                json={
                    "platform": "mastodon",
                    "account_name": "@testuser@mastodon.social",
                    "credentials": {"access_token": "fake-token"},
                },
                headers=headers,
            )
            assert create_resp.status_code == 201
            account_id = create_resp.json()["id"]

            # Delete the account
            delete_resp = await client.delete(
                f"/api/crosspost/accounts/{account_id}",
                headers=headers,
            )
            assert delete_resp.status_code == 204

            # Verify it's gone
            list_resp = await client.get("/api/crosspost/accounts", headers=headers)
            assert list_resp.status_code == 200
            account_ids = [a["id"] for a in list_resp.json()]
            assert account_id not in account_ids
