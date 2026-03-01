"""Tests for AT Protocol OAuth helpers."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey

from backend.crosspost.atproto_oauth import (
    ATProtoOAuthError,
    _is_safe_url,
    create_client_assertion,
    create_dpop_proof,
    create_pkce_challenge,
    discover_auth_server,
    exchange_code_for_tokens,
    generate_es256_keypair,
    load_or_create_keypair,
    refresh_access_token,
    resolve_handle_to_did,
    send_par_request,
    serialize_keypair,
)


async def _always_safe(_url: str) -> bool:
    return True


def _make_fake_ssrf_client_with_mocked_method(method_name: str, mock_fn: object) -> object:
    """Create a fake ssrf_safe_client where one HTTP method is mocked."""

    @asynccontextmanager
    async def fake_ssrf_safe_client(
        timeout: float | httpx.Timeout | None = None,
    ) -> AsyncIterator[httpx.AsyncClient]:
        client = httpx.AsyncClient()
        setattr(client, method_name, lambda *a, **kw: mock_fn(client, *a, **kw))  # type: ignore[operator]
        yield client

    return fake_ssrf_safe_client


class TestES256Keypair:
    def test_generate_returns_private_key_and_jwk(self) -> None:
        private_key, jwk = generate_es256_keypair()
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert "x" in jwk
        assert "y" in jwk
        assert "kid" in jwk
        assert isinstance(private_key.public_key(), EllipticCurvePublicKey)

    def test_serialize_and_load_roundtrip(self, tmp_path) -> None:
        private_key, jwk = generate_es256_keypair()
        path = tmp_path / "key.json"
        serialize_keypair(private_key, jwk, path)
        loaded_key, loaded_jwk = load_or_create_keypair(path)
        assert loaded_jwk["kid"] == jwk["kid"]
        assert loaded_jwk["x"] == jwk["x"]
        # Verify loaded key can sign
        token = jwt.encode({"test": True}, loaded_key, algorithm="ES256")
        decoded = jwt.decode(token, loaded_key.public_key(), algorithms=["ES256"])
        assert decoded["test"] is True

    def test_load_creates_if_missing(self, tmp_path) -> None:
        path = tmp_path / "nonexistent.json"
        assert not path.exists()
        _private_key, jwk = load_or_create_keypair(path)
        assert path.exists()
        assert jwk["kty"] == "EC"

    def test_corrupted_json_regenerates_keypair(self, tmp_path) -> None:
        """A corrupted keypair file must not crash; it should be regenerated."""
        path = tmp_path / "key.json"
        path.write_text("this is not json {{{", encoding="utf-8")
        _private_key, jwk = load_or_create_keypair(path)
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        # File should now contain valid keypair
        data = json.loads(path.read_text())
        assert "private_key_pem" in data

    def test_invalid_key_type_regenerates_keypair(self, tmp_path) -> None:
        """A file with valid JSON but an invalid key should be regenerated."""
        path = tmp_path / "key.json"
        path.write_text(
            json.dumps({"private_key_pem": "not-a-pem", "jwk": {"kty": "bad"}}),
            encoding="utf-8",
        )
        _private_key, jwk = load_or_create_keypair(path)
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"

    def test_missing_jwk_key_regenerates_keypair(self, tmp_path) -> None:
        """A file missing the 'jwk' key should be regenerated."""
        path = tmp_path / "key.json"
        path.write_text(json.dumps({"private_key_pem": "stuff"}), encoding="utf-8")
        _private_key, jwk = load_or_create_keypair(path)
        assert jwk["kty"] == "EC"

    def test_corrupted_file_removed_concurrently_does_not_crash(self, tmp_path) -> None:
        """If another process removes the corrupted file between exists() and unlink(), no crash."""
        from unittest.mock import patch

        path = tmp_path / "key.json"
        path.write_text("this is not json {{{", encoding="utf-8")

        original_unlink = type(path).unlink

        def unlink_that_removes_first(self_path, *, missing_ok=False):
            """Simulate another process removing the file before our unlink()."""
            if self_path == path and self_path.exists():
                original_unlink(self_path)
            original_unlink(self_path, missing_ok=missing_ok)

        with patch.object(type(path), "unlink", unlink_that_removes_first):
            _private_key, jwk = load_or_create_keypair(path)
        assert jwk["kty"] == "EC"


class TestDPoPProof:
    def test_create_dpop_proof_for_auth_server(self) -> None:
        private_key, jwk = generate_es256_keypair()
        proof = create_dpop_proof(
            method="POST",
            url="https://bsky.social/oauth/token",
            key=private_key,
            jwk=jwk,
            nonce="server-nonce-123",
        )
        header = jwt.get_unverified_header(proof)
        assert header["typ"] == "dpop+jwt"
        assert header["alg"] == "ES256"
        assert header["jwk"]["kty"] == "EC"
        payload = jwt.decode(proof, private_key.public_key(), algorithms=["ES256"])
        assert payload["htm"] == "POST"
        assert payload["htu"] == "https://bsky.social/oauth/token"
        assert payload["nonce"] == "server-nonce-123"
        assert "jti" in payload
        assert "iat" in payload
        assert "ath" not in payload

    def test_create_dpop_proof_with_access_token_hash(self) -> None:
        private_key, jwk = generate_es256_keypair()
        access_token = "test-access-token-value"
        proof = create_dpop_proof(
            method="GET",
            url="https://pds.example.com/xrpc/com.atproto.repo.createRecord",
            key=private_key,
            jwk=jwk,
            nonce="nonce-456",
            access_token=access_token,
        )
        payload = jwt.decode(proof, private_key.public_key(), algorithms=["ES256"])
        assert payload["htm"] == "GET"
        assert "ath" in payload
        expected_ath = (
            base64.urlsafe_b64encode(hashlib.sha256(access_token.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert payload["ath"] == expected_ath


class TestPKCE:
    def test_create_pkce_challenge(self) -> None:
        verifier, challenge = create_pkce_challenge()
        assert len(verifier) >= 43
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert challenge == expected


class TestClientAssertion:
    def test_create_client_assertion_jwt(self) -> None:
        private_key, jwk = generate_es256_keypair()
        client_id = "https://myblog.example.com/api/crosspost/bluesky/client-metadata.json"
        aud = "https://bsky.social"
        assertion = create_client_assertion(client_id, aud, private_key, jwk["kid"])
        payload = jwt.decode(
            assertion,
            private_key.public_key(),
            algorithms=["ES256"],
            audience=aud,
        )
        assert payload["iss"] == client_id
        assert payload["sub"] == client_id
        assert payload["aud"] == aud
        assert "jti" in payload
        assert "exp" in payload


class TestHandleResolution:
    async def test_resolve_handle_via_dns_txt(self, monkeypatch) -> None:
        async def mock_dns_resolve(handle):
            return "did:plc:abc123"

        monkeypatch.setattr("backend.crosspost.atproto_oauth._resolve_handle_dns", mock_dns_resolve)
        did = await resolve_handle_to_did("alice.bsky.social")
        assert did == "did:plc:abc123"

    async def test_resolve_handle_via_http_fallback(self, monkeypatch) -> None:
        async def mock_dns_fail(handle):
            return None

        async def mock_http_resolve(handle):
            return "did:plc:http-fallback"

        monkeypatch.setattr("backend.crosspost.atproto_oauth._resolve_handle_dns", mock_dns_fail)
        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth._resolve_handle_http", mock_http_resolve
        )
        did = await resolve_handle_to_did("alice.bsky.social")
        assert did == "did:plc:http-fallback"

    async def test_resolve_handle_fails_when_both_methods_fail(self, monkeypatch) -> None:
        async def mock_fail(handle):
            return None

        monkeypatch.setattr("backend.crosspost.atproto_oauth._resolve_handle_dns", mock_fail)
        monkeypatch.setattr("backend.crosspost.atproto_oauth._resolve_handle_http", mock_fail)
        with pytest.raises(ATProtoOAuthError, match="resolve handle"):
            await resolve_handle_to_did("nonexistent.invalid")


class TestAuthServerDiscovery:
    async def test_discover_auth_server_from_pds(self, monkeypatch) -> None:
        responses = {
            "https://plc.directory/did:plc:abc123": httpx.Response(
                200,
                json={
                    "id": "did:plc:abc123",
                    "service": [
                        {
                            "id": "#atproto_pds",
                            "type": "AtprotoPersonalDataServer",
                            "serviceEndpoint": "https://pds.example.com",
                        }
                    ],
                },
            ),
            "https://pds.example.com/.well-known/oauth-protected-resource": httpx.Response(
                200,
                json={
                    "authorization_servers": ["https://auth.example.com"],
                },
            ),
            "https://auth.example.com/.well-known/oauth-authorization-server": httpx.Response(
                200,
                json={
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/oauth/authorize",
                    "token_endpoint": "https://auth.example.com/oauth/token",
                    "pushed_authorization_request_endpoint": ("https://auth.example.com/oauth/par"),
                    "scopes_supported": ["atproto", "transition:generic"],
                    "dpop_signing_alg_values_supported": ["ES256"],
                    "revocation_endpoint": "https://auth.example.com/oauth/revoke",
                },
            ),
        }

        async def mock_get(self, url, **kwargs):
            if url in responses:
                return responses[url]
            return httpx.Response(404)

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("get", mock_get),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        result = await discover_auth_server("did:plc:abc123")
        assert result["issuer"] == "https://auth.example.com"
        assert result["token_endpoint"] == "https://auth.example.com/oauth/token"
        assert result["pds_url"] == "https://pds.example.com"


class TestPARRequest:
    async def test_send_par_request(self, monkeypatch) -> None:
        private_key, jwk = generate_es256_keypair()

        async def mock_post(self, url, **kwargs):
            assert url == "https://auth.example.com/oauth/par"
            return httpx.Response(
                201,
                json={
                    "request_uri": "urn:ietf:params:oauth:request_uri:abc",
                    "expires_in": 60,
                },
                headers={"DPoP-Nonce": "new-nonce-from-server"},
            )

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("post", mock_post),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        result = await send_par_request(
            auth_server_meta={
                "issuer": "https://auth.example.com",
                "pushed_authorization_request_endpoint": ("https://auth.example.com/oauth/par"),
                "authorization_endpoint": "https://auth.example.com/oauth/authorize",
            },
            client_id="https://myblog.example.com/api/crosspost/bluesky/client-metadata.json",
            redirect_uri="https://myblog.example.com/api/crosspost/bluesky/callback",
            did="did:plc:abc123",
            scope="atproto transition:generic",
            private_key=private_key,
            jwk=jwk,
        )
        assert result["authorization_url"].startswith("https://auth.example.com/oauth/authorize")
        assert "request_uri=" in result["authorization_url"]
        assert "state" in result
        assert "pkce_verifier" in result
        assert "dpop_nonce" in result

    async def test_rejects_unsafe_authorization_endpoint(self, monkeypatch) -> None:
        private_key, jwk = generate_es256_keypair()

        async def selective_safe(url: str) -> bool:
            return url == "https://auth.example.com/oauth/par"

        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", selective_safe)

        with pytest.raises(ATProtoOAuthError, match="Unsafe authorization endpoint"):
            await send_par_request(
                auth_server_meta={
                    "issuer": "https://auth.example.com",
                    "pushed_authorization_request_endpoint": "https://auth.example.com/oauth/par",
                    "authorization_endpoint": "javascript:alert(1)",
                },
                client_id="https://myblog.example.com/api/crosspost/bluesky/client-metadata.json",
                redirect_uri="https://myblog.example.com/api/crosspost/bluesky/callback",
                did="did:plc:abc123",
                scope="atproto transition:generic",
                private_key=private_key,
                jwk=jwk,
            )


class TestTokenExchange:
    async def test_exchange_code_for_tokens(self, monkeypatch) -> None:
        private_key, jwk = generate_es256_keypair()

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "access_token": "at_123",
                    "refresh_token": "rt_456",
                    "token_type": "DPoP",
                    "expires_in": 300,
                    "sub": "did:plc:abc123",
                },
                headers={"DPoP-Nonce": "token-nonce"},
            )

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("post", mock_post),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        result = await exchange_code_for_tokens(
            token_endpoint="https://auth.example.com/oauth/token",
            auth_server_issuer="https://auth.example.com",
            code="auth-code-xyz",
            redirect_uri="https://myblog.example.com/api/crosspost/bluesky/callback",
            pkce_verifier="verifier-abc",
            client_id=("https://myblog.example.com/api/crosspost/bluesky/client-metadata.json"),
            private_key=private_key,
            jwk=jwk,
            dpop_nonce="initial-nonce",
        )
        assert result["access_token"] == "at_123"
        assert result["refresh_token"] == "rt_456"
        assert result["sub"] == "did:plc:abc123"
        assert result["dpop_nonce"] == "token-nonce"

    async def test_refresh_access_token(self, monkeypatch) -> None:
        private_key, jwk = generate_es256_keypair()

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "access_token": "at_new",
                    "refresh_token": "rt_new",
                    "token_type": "DPoP",
                    "expires_in": 300,
                    "sub": "did:plc:abc123",
                },
                headers={"DPoP-Nonce": "refreshed-nonce"},
            )

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("post", mock_post),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        result = await refresh_access_token(
            token_endpoint="https://auth.example.com/oauth/token",
            auth_server_issuer="https://auth.example.com",
            refresh_token="rt_456",
            client_id=("https://myblog.example.com/api/crosspost/bluesky/client-metadata.json"),
            private_key=private_key,
            jwk=jwk,
            dpop_nonce="old-nonce",
        )
        assert result["access_token"] == "at_new"
        assert result["refresh_token"] == "rt_new"
        assert result["dpop_nonce"] == "refreshed-nonce"

    async def test_dpop_nonce_rotation_on_token_exchange(self, monkeypatch) -> None:
        private_key, jwk = generate_es256_keypair()
        call_count = 0

        async def mock_post(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    400,
                    json={"error": "use_dpop_nonce"},
                    headers={"DPoP-Nonce": "server-nonce"},
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "at_rotated",
                    "token_type": "DPoP",
                    "sub": "did:plc:abc123",
                },
                headers={"DPoP-Nonce": "server-nonce"},
            )

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("post", mock_post),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        result = await exchange_code_for_tokens(
            token_endpoint="https://auth.example.com/oauth/token",
            auth_server_issuer="https://auth.example.com",
            code="auth-code",
            redirect_uri="https://myblog.example.com/api/crosspost/bluesky/callback",
            pkce_verifier="verifier",
            client_id="https://myblog.example.com/api/crosspost/bluesky/client-metadata.json",
            private_key=private_key,
            jwk=jwk,
            dpop_nonce="",
        )
        assert call_count == 2
        assert result["access_token"] == "at_rotated"
        assert result["dpop_nonce"] == "server-nonce"

    async def test_dpop_nonce_rotation_handles_non_json_400(self, monkeypatch) -> None:
        """400 response with non-JSON body should not crash during nonce rotation."""
        private_key, jwk = generate_es256_keypair()

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                400,
                text="Bad Request - not JSON",
                headers={"DPoP-Nonce": "new-nonce", "content-type": "text/plain"},
            )

        monkeypatch.setattr(
            "backend.crosspost.atproto_oauth.ssrf_safe_client",
            _make_fake_ssrf_client_with_mocked_method("post", mock_post),
        )
        monkeypatch.setattr("backend.crosspost.atproto_oauth._is_safe_url", _always_safe)
        with pytest.raises(ATProtoOAuthError, match="Token exchange failed"):
            await exchange_code_for_tokens(
                token_endpoint="https://auth.example.com/oauth/token",
                auth_server_issuer="https://auth.example.com",
                code="auth-code",
                redirect_uri="https://myblog.example.com/api/crosspost/bluesky/callback",
                pkce_verifier="verifier",
                client_id="https://myblog.example.com/api/crosspost/bluesky/client-metadata.json",
                private_key=private_key,
                jwk=jwk,
                dpop_nonce="",
            )


class TestKeypairAtomicWrite:
    def test_load_or_create_writes_atomically(self, tmp_path) -> None:
        """Keypair file should have correct permissions and valid content after creation."""
        path = tmp_path / "key.json"
        _private_key, jwk = load_or_create_keypair(path)
        assert path.exists()
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        data = json.loads(path.read_text())
        assert "private_key_pem" in data
        assert "jwk" in data
        assert data["jwk"]["kid"] == jwk["kid"]

    def test_concurrent_creation_produces_valid_keypair(self, tmp_path) -> None:
        """Even if two calls race, the resulting file should be a valid keypair."""
        path = tmp_path / "key.json"
        # First call creates
        _key1, jwk1 = load_or_create_keypair(path)
        # Second call loads existing
        _key2, jwk2 = load_or_create_keypair(path)
        assert jwk1["kid"] == jwk2["kid"]

    def test_concurrent_creation_returns_single_keypair(self, monkeypatch, tmp_path) -> None:
        """Concurrent creators should all observe the same keypair identity."""
        path = tmp_path / "key.json"
        original_serialize = serialize_keypair

        def slow_serialize(private_key, jwk, target_path):
            time.sleep(0.05)
            original_serialize(private_key, jwk, target_path)

        monkeypatch.setattr("backend.crosspost.atproto_oauth.serialize_keypair", slow_serialize)
        barrier = threading.Barrier(8)

        def create_keypair_kid() -> str:
            barrier.wait()
            _key, jwk = load_or_create_keypair(path)
            return str(jwk["kid"])

        with ThreadPoolExecutor(max_workers=8) as executor:
            kids = list(executor.map(lambda _i: create_keypair_kid(), range(8)))

        assert len(set(kids)) == 1


class TestIsSafeUrlAsync:
    async def test_is_safe_url_is_async(self) -> None:
        """_is_safe_url should be a coroutine function (async)."""
        assert inspect.iscoroutinefunction(_is_safe_url)

    async def test_safe_hostname_returns_true(self) -> None:
        """A normal HTTPS URL with a hostname should return True (DNS checked at transport)."""
        result = await _is_safe_url("https://example.com/path")
        assert result is True

    async def test_localhost_returns_false(self) -> None:
        """Localhost URLs should return False."""
        result = await _is_safe_url("https://localhost/path")
        assert result is False

    async def test_private_ip_literal_returns_false(self) -> None:
        """URLs with private IP literals should return False."""
        result = await _is_safe_url("https://192.168.1.1/path")
        assert result is False

    async def test_http_returns_false(self) -> None:
        """Non-HTTPS URLs should return False."""
        result = await _is_safe_url("http://example.com")
        assert result is False

    async def test_loopback_ip_returns_false(self) -> None:
        """URLs with loopback IP should return False."""
        result = await _is_safe_url("https://127.0.0.1/path")
        assert result is False

    async def test_ipv6_localhost_returns_false(self) -> None:
        """IPv6 localhost should return False."""
        result = await _is_safe_url("https://[::1]/path")
        assert result is False
