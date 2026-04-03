"""Tests for Bluesky OAuth API endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from backend.services.crosspost_service import DuplicateAccountError
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from backend.config import Settings


class TestClientMetadata:
    async def test_returns_metadata_when_configured(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        async with create_test_client(test_settings) as client:
            resp = await client.get("/api/crosspost/bluesky/client-metadata.json")
            assert resp.status_code == 200
            data = resp.json()
            assert data["client_id"] == (
                "https://myblog.example.com/api/crosspost/bluesky/client-metadata.json"
            )
            assert data["application_type"] == "web"
            assert data["dpop_bound_access_tokens"] is True
            assert data["token_endpoint_auth_method"] == "private_key_jwt"
            assert "keys" in data["jwks"]
            assert data["jwks"]["keys"][0]["kty"] == "EC"

    async def test_returns_503_when_not_configured(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = ""
        async with create_test_client(test_settings) as client:
            resp = await client.get("/api/crosspost/bluesky/client-metadata.json")
            assert resp.status_code == 503


class TestAuthorizeEndpoint:
    async def test_returns_401_when_not_authenticated(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        async with create_test_client(test_settings) as client:
            resp = await client.post(
                "/api/crosspost/bluesky/authorize",
                json={"handle": "alice.bsky.social"},
            )
            assert resp.status_code == 401


class TestCallbackEndpoint:
    async def test_rejects_invalid_state(self, test_settings: Settings) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"
        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/bluesky/callback",
                params={"code": "test-code", "state": "invalid-state"},
                follow_redirects=False,
            )
            assert resp.status_code == 400

    async def test_rejects_callback_with_missing_iss(
        self, test_settings: Settings, monkeypatch
    ) -> None:
        """Regression: missing iss parameter must be rejected (issuer confusion attack)."""
        test_settings.bluesky_client_url = "https://myblog.example.com"

        pending_state = {
            "pkce_verifier": "pkce-verifier",
            "dpop_nonce": "nonce",
            "user_id": 123,
            "did": "did:plc:abc123",
            "handle": "alice.bsky.social",
            "auth_server_meta": {
                "issuer": "https://auth.example.com",
                "token_endpoint": "https://auth.example.com/oauth/token",
                "pds_url": "https://pds.example.com",
            },
        }

        def mock_pop(_store: object, state: str) -> dict[str, object] | None:
            if state == "valid-state":
                return pending_state
            return None

        monkeypatch.setattr("backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop", mock_pop)

        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/bluesky/callback",
                params={"code": "auth-code", "state": "valid-state"},
                follow_redirects=False,
            )

        assert resp.status_code == 400
        assert "Issuer mismatch" in resp.json()["detail"]

    async def test_rejects_callback_with_wrong_iss(
        self, test_settings: Settings, monkeypatch
    ) -> None:
        """Regression: wrong iss parameter must be rejected (issuer confusion attack)."""
        test_settings.bluesky_client_url = "https://myblog.example.com"

        pending_state = {
            "pkce_verifier": "pkce-verifier",
            "dpop_nonce": "nonce",
            "user_id": 123,
            "did": "did:plc:abc123",
            "handle": "alice.bsky.social",
            "auth_server_meta": {
                "issuer": "https://auth.example.com",
                "token_endpoint": "https://auth.example.com/oauth/token",
                "pds_url": "https://pds.example.com",
            },
        }

        def mock_pop(_store: object, state: str) -> dict[str, object] | None:
            if state == "valid-state":
                return pending_state
            return None

        monkeypatch.setattr("backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop", mock_pop)

        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/bluesky/callback",
                params={
                    "code": "auth-code",
                    "state": "valid-state",
                    "iss": "https://evil.example.com",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 400
        assert "Issuer mismatch" in resp.json()["detail"]

    async def test_duplicate_account_only_replaces_matching_handle(
        self, test_settings: Settings, monkeypatch
    ) -> None:
        test_settings.bluesky_client_url = "https://myblog.example.com"

        pending_state = {
            "pkce_verifier": "pkce-verifier",
            "dpop_nonce": "nonce-before",
            "user_id": 123,
            "did": "did:plc:abc123",
            "handle": "alice.bsky.social",
            "auth_server_meta": {
                "issuer": "https://auth.example.com",
                "token_endpoint": "https://auth.example.com/oauth/token",
                "pds_url": "https://pds.example.com",
            },
        }

        pop_calls: list[str] = []

        def mock_pop(_store: object, state: str) -> dict[str, object] | None:
            pop_calls.append(state)
            if state == "state-1":
                return pending_state
            return None

        async def mock_exchange_code_for_tokens(**_kwargs):
            return {
                "access_token": "at_valid",
                "refresh_token": "rt_valid",
                "sub": "did:plc:abc123",
                "dpop_nonce": "nonce-after",
            }

        create_attempts = 0

        async def mock_create_social_account(*_args, **_kwargs):
            nonlocal create_attempts
            create_attempts += 1
            if create_attempts == 1:
                raise DuplicateAccountError("already exists")
            return SimpleNamespace(
                id=999,
                platform="bluesky",
                account_name="alice.bsky.social",
                created_at="2026-01-01T00:00:00+00:00",
            )

        async def mock_get_social_accounts(*_args, **_kwargs):
            return [
                SimpleNamespace(id=10, platform="bluesky", account_name="alice.bsky.social"),
                SimpleNamespace(id=11, platform="bluesky", account_name="bob.bsky.social"),
                SimpleNamespace(id=12, platform="mastodon", account_name="alice"),
            ]

        deleted_ids: list[int] = []

        async def mock_delete_social_account(_session, account_id: int, _user_id: int) -> bool:
            deleted_ids.append(account_id)
            return True

        monkeypatch.setattr("backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop", mock_pop)
        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.exchange_code_for_tokens",
            mock_exchange_code_for_tokens,
        )
        monkeypatch.setattr(
            "backend.api.crosspost.create_social_account", mock_create_social_account
        )
        monkeypatch.setattr("backend.api.crosspost.get_social_accounts", mock_get_social_accounts)
        monkeypatch.setattr(
            "backend.api.crosspost.delete_social_account", mock_delete_social_account
        )

        async with create_test_client(test_settings) as client:
            resp = await client.get(
                "/api/crosspost/bluesky/callback",
                params={"code": "auth-code", "state": "state-1", "iss": "https://auth.example.com"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert pop_calls == ["state-1"]
        assert create_attempts == 2
        assert deleted_ids == [10]
