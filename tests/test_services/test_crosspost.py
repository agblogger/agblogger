"""Tests for cross-posting base classes and formatting."""

from __future__ import annotations

import json as json_mod

import httpx
import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from backend.crosspost.atproto_oauth import generate_es256_keypair
from backend.crosspost.base import CrossPostContent
from backend.crosspost.bluesky import BlueskyCrossPoster, _build_post_text, _find_facets
from backend.crosspost.facebook import (
    FacebookCrossPoster,
    FacebookOAuthTokenError,
    _build_facebook_text,
    exchange_facebook_oauth_token,
)
from backend.crosspost.http_utils import parse_json_object, require_str_field
from backend.crosspost.mastodon import (
    MastodonCrossPoster,
    MastodonOAuthTokenError,
    _build_status_text,
    exchange_mastodon_oauth_token,
)
from backend.crosspost.registry import list_platforms
from backend.crosspost.x import (
    X_CHAR_LIMIT,
    XCrossPoster,
    XOAuthTokenError,
    _build_tweet_text,
    exchange_x_oauth_token,
)


class TestRequireStrField:
    """require_str_field extracts and validates string fields from dicts."""

    def test_returns_value_when_present_and_string(self) -> None:
        assert require_str_field({"key": "val"}, "key", context="test") == "val"

    def test_raises_when_missing(self) -> None:
        with pytest.raises(ValueError, match=r"test.*missing.*key"):
            require_str_field({}, "key", context="test")

    def test_raises_when_not_string(self) -> None:
        with pytest.raises(ValueError, match=r"test.*missing.*key"):
            require_str_field({"key": 123}, "key", context="test")

    def test_raises_when_empty_string(self) -> None:
        with pytest.raises(ValueError, match=r"test.*missing.*key"):
            require_str_field({"key": ""}, "key", context="test")

    def test_custom_error_cls(self) -> None:
        with pytest.raises(RuntimeError, match=r"missing"):
            require_str_field({}, "key", context="test", error_cls=RuntimeError)


class TestBlueSkyFormatting:
    def test_build_post_text_short(self) -> None:
        content = CrossPostContent(
            title="Test Post",
            excerpt="Short excerpt.",
            url="https://blog.example.com/posts/test",
            labels=["swe", "ai"],
        )
        text = _build_post_text(content)
        assert "Short excerpt." in text
        assert "#swe" in text
        assert "#ai" in text
        assert "https://blog.example.com/posts/test" in text
        assert len(text) <= 300

    def test_build_post_text_long_truncation(self) -> None:
        content = CrossPostContent(
            title="Test Post",
            excerpt="A" * 500,
            url="https://blog.example.com/posts/test",
            labels=["swe"],
        )
        text = _build_post_text(content)
        assert len(text) <= 300
        assert "..." in text

    def test_build_post_text_uses_custom_text(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="My custom post text!",
        )
        text = _build_post_text(content)
        assert text == "My custom post text!"

    def test_build_post_text_rejects_custom_text_over_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 301,
        )
        with pytest.raises(ValueError, match="300"):
            _build_post_text(content)

    def test_build_post_text_accepts_custom_text_at_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 300,
        )
        text = _build_post_text(content)
        assert text == "A" * 300

    def test_find_facets_link(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://blog.example.com",
            labels=[],
        )
        text = "Hello\n\nhttps://blog.example.com"
        facets = _find_facets(text, content)
        assert len(facets) >= 1
        link_facet = facets[0]
        assert link_facet["features"][0]["$type"] == "app.bsky.richtext.facet#link"

    def test_find_facets_hashtags(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://blog.example.com",
            labels=["swe", "ai"],
        )
        text = "Hello\n\n#swe #ai\nhttps://blog.example.com"
        facets = _find_facets(text, content)
        types = [f["features"][0]["$type"] for f in facets]
        assert "app.bsky.richtext.facet#tag" in types


class TestRegistry:
    def test_list_platforms(self) -> None:
        platforms = list_platforms()
        assert "bluesky" in platforms
        assert "mastodon" in platforms
        assert "x" in platforms
        assert "facebook" in platforms
        assert len(platforms) >= 4


class TestMastodonUrlValidation:
    @pytest.mark.asyncio
    async def test_authenticate_rejects_localhost_instance_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http:// scheme is rejected by _normalize_instance_url, no network call made."""
        requested_urls: list[str] = []

        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "1", "acct": "tester"}

        class FakeClient:
            async def get(self, url: str, **kwargs) -> DummyResponse:
                requested_urls.append(url)
                return DummyResponse()

            async def post(self, url: str, **kwargs) -> DummyResponse:
                requested_urls.append(url)
                return DummyResponse()

        from tests.test_services._ssrf_helpers import make_fake_ssrf_safe_client

        monkeypatch.setattr(
            "backend.crosspost.mastodon.ssrf_safe_client",
            make_fake_ssrf_safe_client(FakeClient),
        )

        poster = MastodonCrossPoster()
        is_ok = await poster.authenticate(
            {"access_token": "token", "instance_url": "http://127.0.0.1:8080"}
        )
        assert is_ok is False
        assert requested_urls == []

    @pytest.mark.asyncio
    async def test_authenticate_accepts_public_https_instance_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        requested_urls: list[str] = []

        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "1", "acct": "tester"}

        class FakeClient:
            async def get(self, url: str, **kwargs) -> DummyResponse:
                requested_urls.append(url)
                return DummyResponse()

            async def post(self, url: str, **kwargs) -> DummyResponse:
                requested_urls.append(url)
                return DummyResponse()

        from tests.test_services._ssrf_helpers import make_fake_ssrf_safe_client

        monkeypatch.setattr(
            "backend.crosspost.mastodon.ssrf_safe_client",
            make_fake_ssrf_safe_client(FakeClient),
        )

        poster = MastodonCrossPoster()
        is_ok = await poster.authenticate(
            {"access_token": "token", "instance_url": "https://93.184.216.34"}
        )
        assert is_ok is True
        assert requested_urls == ["https://93.184.216.34/api/v1/accounts/verify_credentials"]


class TestMastodonFormatting:
    def test_build_status_text_uses_custom_text(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="My custom Mastodon text!",
        )
        text = _build_status_text(content)
        assert text == "My custom Mastodon text!"

    def test_build_status_text_rejects_custom_text_over_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 501,
        )
        with pytest.raises(ValueError, match="500"):
            _build_status_text(content)

    def test_build_status_text_accepts_custom_text_at_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 500,
        )
        text = _build_status_text(content)
        assert text == "A" * 500


class TestMastodonOAuthTokenExchange:
    async def test_raises_on_missing_access_token_in_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Token response with 200 but no access_token should raise MastodonOAuthTokenError."""

        class DummyResponse:
            status_code = 200
            text = '{"error": "something"}'

            @staticmethod
            def json() -> dict[str, str]:
                return {"error": "something"}

        class FakeClient:
            async def post(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        from tests.test_services._ssrf_helpers import make_fake_ssrf_safe_client

        monkeypatch.setattr(
            "backend.crosspost.mastodon.ssrf_safe_client",
            make_fake_ssrf_safe_client(FakeClient),
        )
        monkeypatch.setattr(
            "backend.crosspost.mastodon._normalize_instance_url",
            lambda u: "https://mastodon.social",
        )

        with pytest.raises(MastodonOAuthTokenError, match="access_token"):
            await exchange_mastodon_oauth_token(
                instance_url="https://mastodon.social",
                code="test-code",
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.com/callback",
                pkce_verifier="test-verifier",
            )

    async def test_raises_on_non_json_token_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class DummyResponse:
            status_code = 200
            text = "<html>bad gateway</html>"

            @staticmethod
            def json() -> dict[str, str]:
                raise ValueError("not json")

        class FakeClient:
            async def post(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        from tests.test_services._ssrf_helpers import make_fake_ssrf_safe_client

        monkeypatch.setattr(
            "backend.crosspost.mastodon.ssrf_safe_client",
            make_fake_ssrf_safe_client(FakeClient),
        )
        monkeypatch.setattr(
            "backend.crosspost.mastodon._normalize_instance_url",
            lambda u: "https://mastodon.social",
        )

        with pytest.raises(MastodonOAuthTokenError, match="non-JSON"):
            await exchange_mastodon_oauth_token(
                instance_url="https://mastodon.social",
                code="test-code",
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.com/callback",
                pkce_verifier="test-verifier",
            )


def _make_oauth_credentials() -> dict[str, str]:
    """Build a complete set of OAuth credentials for testing."""
    private_key, jwk = generate_es256_keypair()
    pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    return {
        "access_token": "at_valid",
        "did": "did:plc:abc123",
        "handle": "alice.bsky.social",
        "pds_url": "https://pds.example.com",
        "dpop_private_key_pem": pem,
        "dpop_jwk": json_mod.dumps(jwk),
        "dpop_nonce": "nonce-1",
        "auth_server_issuer": "https://bsky.social",
        "token_endpoint": "https://bsky.social/oauth/token",
        "refresh_token": "rt_valid",
        "client_id": "https://myblog.example.com/api/crosspost/bluesky/client-metadata.json",
    }


class TestBlueskyCrossPosterOAuth:
    async def test_authenticate_with_oauth_tokens(self) -> None:
        creds = _make_oauth_credentials()
        poster = BlueskyCrossPoster()
        result = await poster.authenticate(creds)
        assert result is True

    async def test_authenticate_rejects_missing_fields(self) -> None:
        poster = BlueskyCrossPoster()
        result = await poster.authenticate({"access_token": "at_valid"})
        assert result is False

    async def test_authenticate_corrupted_pem_key_returns_false(self) -> None:
        creds = _make_oauth_credentials()
        creds["dpop_private_key_pem"] = "not-a-valid-pem"
        poster = BlueskyCrossPoster()
        result = await poster.authenticate(creds)
        assert result is False

    async def test_authenticate_invalid_dpop_jwk_json_returns_false(self) -> None:
        creds = _make_oauth_credentials()
        creds["dpop_jwk"] = "{not valid json"
        poster = BlueskyCrossPoster()
        result = await poster.authenticate(creds)
        assert result is False

    async def test_post_uses_dpop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_headers: dict[str, str] = {}

        class FakeClient:
            async def post(self, url: str, **kwargs: object) -> httpx.Response:
                headers = kwargs.get("headers", {})
                assert isinstance(headers, dict)
                captured_headers.update(headers)
                return httpx.Response(
                    200,
                    json={
                        "uri": "at://did:plc:abc123/app.bsky.feed.post/abc",
                        "cid": "bafy123",
                    },
                    headers={"DPoP-Nonce": "nonce-updated"},
                )

            async def get(self, url: str, **kwargs: object) -> httpx.Response:
                return httpx.Response(200, json={})

        from tests.test_services._ssrf_helpers import make_fake_ssrf_safe_client

        monkeypatch.setattr(
            "backend.crosspost.bluesky.ssrf_safe_client",
            make_fake_ssrf_safe_client(FakeClient),
        )

        poster = BlueskyCrossPoster()
        await poster.authenticate(_make_oauth_credentials())
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://blog.example.com/post",
            labels=["swe"],
        )
        result = await poster.post(content)
        assert result.success
        assert captured_headers.get("Authorization", "").startswith("DPoP ")
        assert "DPoP" in captured_headers


class TestXFormatting:
    def test_build_tweet_text_short(self) -> None:
        content = CrossPostContent(
            title="Test Post",
            excerpt="Short excerpt.",
            url="https://blog.example.com/posts/test",
            labels=["swe", "ai"],
        )
        text = _build_tweet_text(content)
        assert "Short excerpt." in text
        assert "#swe" in text
        assert "#ai" in text
        assert "https://blog.example.com/posts/test" in text
        assert len(text) <= X_CHAR_LIMIT

    def test_build_tweet_text_long_truncation(self) -> None:
        content = CrossPostContent(
            title="Test Post",
            excerpt="A" * 500,
            url="https://blog.example.com/posts/test",
            labels=["swe"],
        )
        text = _build_tweet_text(content)
        assert len(text) <= X_CHAR_LIMIT
        assert "..." in text

    def test_build_tweet_text_uses_custom_text(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="My custom tweet!",
        )
        text = _build_tweet_text(content)
        assert text == "My custom tweet!"

    def test_build_tweet_text_rejects_custom_text_over_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 281,
        )
        with pytest.raises(ValueError, match="280"):
            _build_tweet_text(content)

    def test_build_tweet_text_accepts_custom_text_at_limit(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="A" * 280,
        )
        text = _build_tweet_text(content)
        assert text == "A" * 280


class TestXCrossPoster:
    async def test_authenticate_with_valid_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        result = await poster.authenticate(
            {
                "access_token": "test_token",
                "refresh_token": "test_rt",
                "username": "testuser",
            }
        )
        assert result is True

    async def test_authenticate_rejects_missing_token(self) -> None:
        poster = XCrossPoster()
        result = await poster.authenticate({"refresh_token": "rt"})
        assert result is False

    async def test_post_creates_tweet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        class DummyResponse:
            status_code = 201
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "1234567890", "text": "Hello"}}

        class DummyVerifyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyVerifyResponse:
                return DummyVerifyResponse()

            async def post(self, url: str, **kwargs) -> DummyResponse:
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        await poster.authenticate(
            {
                "access_token": "test_token",
                "refresh_token": "test_rt",
                "username": "testuser",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello world",
            url="https://blog.example.com/post",
            labels=["swe"],
        )
        result = await poster.post(content)
        assert result.success
        assert result.platform_id == "1234567890"
        assert captured["url"] == "https://api.x.com/2/tweets"

    async def test_post_refreshes_on_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        class DummyRefreshResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "new_at", "refresh_token": "new_rt"}

        class DummyTweetResponse:
            status_code = 201
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "999", "text": "Hello"}}

        class Dummy401Response:
            status_code = 401
            text = "Unauthorized"

            @staticmethod
            def json() -> dict[str, str]:
                return {"detail": "Unauthorized"}

        class DummyVerifyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyVerifyResponse:
                return DummyVerifyResponse()

            async def post(self, url: str, **kwargs) -> object:
                nonlocal call_count
                call_count += 1
                if url == "https://api.x.com/2/oauth2/token":
                    return DummyRefreshResponse()
                if call_count == 1:
                    return Dummy401Response()
                return DummyTweetResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        await poster.authenticate(
            {
                "access_token": "old_at",
                "refresh_token": "old_rt",
                "username": "testuser",
                "client_id": "test_client_id",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://example.com/post",
            labels=[],
        )
        result = await poster.post(content)
        assert result.success
        updated = poster.get_updated_credentials()
        assert updated is not None
        assert updated["access_token"] == "new_at"


class TestXOAuthTokenExchange:
    """Tests for exchange_x_oauth_token function (Issue #3, #10)."""

    async def test_raises_on_token_exchange_failure_with_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #10: Error message should include response body details."""

        class DummyResponse:
            status_code = 400
            text = '{"detail": "Invalid PKCE verifier"}'

            @staticmethod
            def json() -> dict[str, str]:
                return {"detail": "Invalid PKCE verifier"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(XOAuthTokenError, match="Invalid PKCE verifier"):
            await exchange_x_oauth_token(
                code="test-code",
                client_id="cid",
                client_secret="csec",
                redirect_uri="https://example.com/cb",
                pkce_verifier="verifier",
            )

    async def test_raises_on_missing_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Issue #3: Should raise error when username is missing, not fall back to 'unknown'."""
        call_count = 0

        class DummyTokenResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "at", "refresh_token": "rt"}

        class DummyUserResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123"}}  # No username field

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyTokenResponse:
                return DummyTokenResponse()

            async def get(self, url: str, **kwargs) -> DummyUserResponse:
                nonlocal call_count
                call_count += 1
                return DummyUserResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(XOAuthTokenError, match="username"):
            await exchange_x_oauth_token(
                code="test-code",
                client_id="cid",
                client_secret="csec",
                redirect_uri="https://example.com/cb",
                pkce_verifier="verifier",
            )

    async def test_happy_path_returns_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Happy path: returns credentials with username."""

        class DummyTokenResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "at_123", "refresh_token": "rt_456"}

        class DummyUserResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyTokenResponse:
                return DummyTokenResponse()

            async def get(self, url: str, **kwargs) -> DummyUserResponse:
                return DummyUserResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        result = await exchange_x_oauth_token(
            code="test-code",
            client_id="cid",
            client_secret="csec",
            redirect_uri="https://example.com/cb",
            pkce_verifier="verifier",
        )
        assert result["access_token"] == "at_123"
        assert result["refresh_token"] == "rt_456"
        assert result["username"] == "testuser"

    async def test_raises_on_user_fetch_failure_with_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #10: User fetch error should include response body details."""

        class DummyTokenResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "at", "refresh_token": "rt"}

        class DummyUserResponse:
            status_code = 403
            text = '{"detail": "Forbidden"}'

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyTokenResponse:
                return DummyTokenResponse()

            async def get(self, url: str, **kwargs) -> DummyUserResponse:
                return DummyUserResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(XOAuthTokenError, match="Forbidden"):
            await exchange_x_oauth_token(
                code="test-code",
                client_id="cid",
                client_secret="csec",
                redirect_uri="https://example.com/cb",
                pkce_verifier="verifier",
            )

    async def test_raises_on_non_json_user_profile_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class DummyTokenResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "at", "refresh_token": "rt"}

        class DummyUserResponse:
            status_code = 200
            text = "<html>oops</html>"

            @staticmethod
            def json() -> dict[str, object]:
                raise ValueError("not json")

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyTokenResponse:
                return DummyTokenResponse()

            async def get(self, url: str, **kwargs) -> DummyUserResponse:
                return DummyUserResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(XOAuthTokenError, match="non-JSON"):
            await exchange_x_oauth_token(
                code="test-code",
                client_id="cid",
                client_secret="csec",
                redirect_uri="https://example.com/cb",
                pkce_verifier="verifier",
            )


class TestXTokenRefresh:
    """Tests for XCrossPoster._try_refresh_token (Issues #5, #12)."""

    async def test_refresh_uses_basic_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Issue #5: Token refresh should use HTTP Basic Auth, matching initial exchange."""
        captured_kwargs: dict[str, object] = {}

        class DummyVerifyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyRefreshResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "new_at", "refresh_token": "new_rt"}

        class Dummy401Response:
            status_code = 401
            text = "Unauthorized"

            @staticmethod
            def json() -> dict[str, str]:
                return {"detail": "Unauthorized"}

        class DummyTweetResponse:
            status_code = 201
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "999", "text": "Hello"}}

        call_count = 0

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyVerifyResponse:
                return DummyVerifyResponse()

            async def post(self, url: str, **kwargs) -> object:
                nonlocal call_count
                call_count += 1
                if url == "https://api.x.com/2/oauth2/token":
                    captured_kwargs.update(kwargs)
                    return DummyRefreshResponse()
                if call_count == 1:
                    return Dummy401Response()
                return DummyTweetResponse()

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        await poster.authenticate(
            {
                "access_token": "old_at",
                "refresh_token": "old_rt",
                "username": "testuser",
                "client_id": "test_cid",
                "client_secret": "test_csec",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://example.com/post",
            labels=[],
        )
        await poster.post(content)

        # Verify Basic Auth was used
        auth = captured_kwargs.get("auth")
        assert auth is not None, "Token refresh should use HTTP Basic Auth"
        assert auth == ("test_cid", "test_csec")

    async def test_refresh_handles_missing_access_token_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #12: Missing access_token in refresh response should not raise KeyError."""

        class DummyVerifyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"id": "123", "username": "testuser"}}

        class DummyRefreshResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"token_type": "bearer"}  # Missing access_token

        class Dummy401Response:
            status_code = 401
            text = "Unauthorized"

            @staticmethod
            def json() -> dict[str, str]:
                return {"detail": "Unauthorized"}

        call_count = 0

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyVerifyResponse:
                return DummyVerifyResponse()

            async def post(self, url: str, **kwargs) -> object:
                nonlocal call_count
                call_count += 1
                if url == "https://api.x.com/2/oauth2/token":
                    return DummyRefreshResponse()
                if call_count == 1:
                    return Dummy401Response()
                return Dummy401Response()  # Still fails after refresh

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        await poster.authenticate(
            {
                "access_token": "old_at",
                "refresh_token": "old_rt",
                "username": "testuser",
                "client_id": "test_cid",
                "client_secret": "test_csec",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello",
            url="https://example.com/post",
            labels=[],
        )
        # Should not raise KeyError - should return failure result
        result = await poster.post(content)
        assert result.success is False


class TestXValidateCredentials:
    """Tests for XCrossPoster.validate_credentials (Issue #9)."""

    async def test_logs_warning_on_network_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue #9: Network errors should be logged, not silently swallowed."""

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> None:
                raise httpx.ConnectTimeout("Connection timed out")

        monkeypatch.setattr("backend.crosspost.x.httpx.AsyncClient", DummyAsyncClient)

        poster = XCrossPoster()
        poster._access_token = "test_token"

        import logging

        with caplog.at_level(logging.WARNING, logger="backend.crosspost.x"):
            result = await poster.validate_credentials()

        assert result is False
        assert any("ConnectTimeout" in msg for msg in caplog.messages)


class TestXTruncationEdgeCases:
    """Tests for CR-1: Tweet text truncation edge cases."""

    def test_very_long_url_and_hashtags_produces_empty_excerpt(self) -> None:
        """When URL + hashtags fill the limit, excerpt should be empty, not awkward."""
        long_url = "https://blog.example.com/posts/" + "a" * 200
        content = CrossPostContent(
            title="Test",
            excerpt="Hello world this is a test",
            url=long_url,
            labels=["swe", "ai", "ml", "data", "tech"],
        )
        text = _build_tweet_text(content)
        assert len(text) <= X_CHAR_LIMIT
        # Should not contain single-character excerpt fragments
        lines = text.split("\n\n", 1)
        # First part is the excerpt - it should be empty or reasonable, not single chars
        if lines[0]:
            assert len(lines[0]) >= 3 or lines[0] == ""


class TestFacebookFormatting:
    def test_build_facebook_text_includes_parts(self) -> None:
        content = CrossPostContent(
            title="Test Post",
            excerpt="Short excerpt.",
            url="https://blog.example.com/posts/test",
            labels=["swe", "ai"],
        )
        text = _build_facebook_text(content)
        assert "Short excerpt." in text
        assert "#swe" in text
        assert "#ai" in text

    def test_build_facebook_text_uses_custom_text(self) -> None:
        content = CrossPostContent(
            title="Test",
            excerpt="Excerpt.",
            url="https://example.com/posts/test",
            custom_text="My custom Facebook post!",
        )
        text = _build_facebook_text(content)
        assert text == "My custom Facebook post!"


class TestFacebookCrossPoster:
    async def test_authenticate_with_valid_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345", "name": "My Page"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        result = await poster.authenticate(
            {
                "page_access_token": "test_token",
                "page_id": "12345",
                "page_name": "My Page",
            }
        )
        assert result is True

    async def test_authenticate_rejects_missing_token(self) -> None:
        poster = FacebookCrossPoster()
        result = await poster.authenticate({"page_id": "12345"})
        assert result is False

    async def test_authenticate_rejects_missing_page_id(self) -> None:
        poster = FacebookCrossPoster()
        result = await poster.authenticate({"page_access_token": "test"})
        assert result is False

    async def test_post_to_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        class DummyGetResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345", "name": "My Page"}

        class DummyPostResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345_67890"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyGetResponse:
                return DummyGetResponse()

            async def post(self, url: str, **kwargs) -> DummyPostResponse:
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                captured["headers"] = kwargs.get("headers")
                return DummyPostResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        await poster.authenticate(
            {
                "page_access_token": "test_token",
                "page_id": "12345",
                "page_name": "My Page",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello world",
            url="https://blog.example.com/post",
            labels=["swe"],
        )
        result = await poster.post(content)
        assert result.success
        assert result.platform_id == "12345_67890"
        assert "12345" in str(captured["url"])
        # Issue #4: Verify access token is NOT in the JSON body
        json_body = captured["json"]
        assert isinstance(json_body, dict)
        assert json_body["link"] == "https://blog.example.com/post"
        assert "access_token" not in json_body

    async def test_post_uses_authorization_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Issue #4: Access token should be in Authorization header, not request body."""
        captured_headers: dict[str, str] = {}

        class DummyGetResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345", "name": "My Page"}

        class DummyPostResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345_67890"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyGetResponse:
                return DummyGetResponse()

            async def post(self, url: str, **kwargs) -> DummyPostResponse:
                headers = kwargs.get("headers", {})
                assert isinstance(headers, dict)
                captured_headers.update(headers)
                return DummyPostResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        await poster.authenticate(
            {
                "page_access_token": "secret_token",
                "page_id": "12345",
                "page_name": "My Page",
            }
        )
        content = CrossPostContent(
            title="Test",
            excerpt="Hello world",
            url="https://blog.example.com/post",
            labels=["swe"],
        )
        await poster.post(content)
        assert captured_headers.get("Authorization") == "Bearer secret_token"

    async def test_authenticate_validates_token_via_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #7: authenticate() should validate the token against the API."""
        requested_urls: list[str] = []

        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"id": "12345", "name": "My Page"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyResponse:
                requested_urls.append(url)
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        result = await poster.authenticate(
            {
                "page_access_token": "test_token",
                "page_id": "12345",
                "page_name": "My Page",
            }
        )
        assert result is True
        # Should have made an API call to verify the token
        assert len(requested_urls) == 1
        assert "12345" in requested_urls[0]

    async def test_authenticate_returns_false_on_invalid_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #7: authenticate() should return False if API rejects the token."""

        class DummyResponse:
            status_code = 401
            text = "Invalid token"

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        result = await poster.authenticate(
            {
                "page_access_token": "bad_token",
                "page_id": "12345",
                "page_name": "My Page",
            }
        )
        assert result is False


class TestFacebookOAuthTokenExchange:
    """Tests for exchange_facebook_oauth_token (Issues #8, #10)."""

    async def test_raises_on_token_exchange_failure_with_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #10: Error should include response body details."""

        class DummyResponse:
            status_code = 400
            text = '{"error": "invalid_grant"}'

            @staticmethod
            def json() -> dict[str, str]:
                return {"error": "invalid_grant"}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(FacebookOAuthTokenError, match="invalid_grant"):
            await exchange_facebook_oauth_token(
                code="test-code",
                app_id="app_123",
                app_secret="secret",
                redirect_uri="https://example.com/cb",
            )

    async def test_raises_on_long_lived_token_missing_access_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #8: Should warn/raise when long-lived token response lacks access_token."""
        call_count = 0

        class DummyShortTokenResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "short_token"}

        class DummyLongLivedResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"token_type": "bearer"}  # Missing access_token

        class DummyPagesResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, list[dict[str, str]]]:
                return {"data": [{"id": "pg1", "name": "Page", "access_token": "pat"}]}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> object:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return DummyShortTokenResp()
                return DummyLongLivedResp()

            async def get(self, url: str, **kwargs) -> object:
                return DummyPagesResp()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(FacebookOAuthTokenError, match="access_token"):
            await exchange_facebook_oauth_token(
                code="test-code",
                app_id="app_123",
                app_secret="secret",
                redirect_uri="https://example.com/cb",
            )

    async def test_happy_path_returns_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Happy path: returns user token and pages."""
        call_count = 0
        captured_calls: list[tuple[str, str, dict[str, object]]] = []

        class DummyShortTokenResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "short_token"}

        class DummyLongLivedResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, str]:
                return {"access_token": "long_lived_token"}

        class DummyPagesResp:
            status_code = 200
            text = ""

            @staticmethod
            def json() -> dict[str, list[dict[str, str]]]:
                return {"data": [{"id": "pg1", "name": "My Page", "access_token": "pat1"}]}

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> object:
                nonlocal call_count
                call_count += 1
                captured_calls.append(("post", url, kwargs))
                if call_count == 1:
                    return DummyShortTokenResp()
                return DummyLongLivedResp()

            async def get(self, url: str, **kwargs) -> object:
                captured_calls.append(("get", url, kwargs))
                return DummyPagesResp()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        result = await exchange_facebook_oauth_token(
            code="test-code",
            app_id="app_123",
            app_secret="secret",
            redirect_uri="https://example.com/cb",
        )
        assert result["user_access_token"] == "long_lived_token"
        pages = result["pages"]
        assert isinstance(pages, list)
        assert len(pages) == 1
        assert captured_calls[0][0] == "post"
        assert captured_calls[1][0] == "post"
        assert "params" not in captured_calls[0][2]
        assert "params" not in captured_calls[1][2]
        assert captured_calls[2][2].get("headers") == {"Authorization": "Bearer long_lived_token"}
        assert "params" not in captured_calls[2][2]

    async def test_raises_on_non_json_token_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class DummyResponse:
            status_code = 200
            text = "<html>proxy error</html>"

            @staticmethod
            def json() -> dict[str, str]:
                raise ValueError("not json")

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url: str, **kwargs) -> DummyResponse:
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        with pytest.raises(FacebookOAuthTokenError, match="non-JSON"):
            await exchange_facebook_oauth_token(
                code="test-code",
                app_id="app_123",
                app_secret="secret",
                redirect_uri="https://example.com/cb",
            )


class TestFacebookValidateCredentials:
    """Tests for FacebookCrossPoster.validate_credentials (Issue #9)."""

    async def test_logs_warning_on_network_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue #9: Network errors should be logged, not silently swallowed."""

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> None:
                raise httpx.ConnectTimeout("Connection timed out")

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        poster._page_access_token = "test_token"

        import logging

        with caplog.at_level(logging.WARNING, logger="backend.crosspost.facebook"):
            result = await poster.validate_credentials()

        assert result is False
        assert any("ConnectTimeout" in msg for msg in caplog.messages)

    async def test_uses_authorization_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Issue #4: validate_credentials should use Authorization header."""
        captured_kwargs: dict[str, object] = {}

        class DummyResponse:
            status_code = 200

        class DummyAsyncClient:
            async def __aenter__(self) -> DummyAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url: str, **kwargs) -> DummyResponse:
                captured_kwargs.update(kwargs)
                return DummyResponse()

        monkeypatch.setattr("backend.crosspost.facebook.httpx.AsyncClient", DummyAsyncClient)

        poster = FacebookCrossPoster()
        poster._page_access_token = "secret_token"
        poster._page_id = "12345"
        await poster.validate_credentials()

        headers = captured_kwargs.get("headers", {})
        assert isinstance(headers, dict)
        assert headers.get("Authorization") == "Bearer secret_token"
        # Should NOT pass token as query param
        params = captured_kwargs.get("params", {})
        assert isinstance(params, dict)
        assert "access_token" not in params


class TestParseJsonObject:
    """Tests for the shared parse_json_object utility."""

    def _make_response(self, body: str, status_code: int = 200) -> httpx.Response:
        return httpx.Response(status_code=status_code, text=body)

    def test_valid_dict_returns_parsed(self) -> None:
        resp = self._make_response('{"key": "value"}')
        result = parse_json_object(resp, context="test endpoint")
        assert result == {"key": "value"}

    def test_valid_dict_with_error_cls(self) -> None:
        resp = self._make_response('{"key": "value"}')
        result = parse_json_object(resp, error_cls=ValueError, context="test endpoint")
        assert result == {"key": "value"}

    def test_non_json_without_error_cls_raises_valueerror(self) -> None:
        resp = self._make_response("not json")
        with pytest.raises(ValueError, match="test endpoint"):
            parse_json_object(resp, context="test endpoint")

    def test_non_json_with_error_cls_raises_error_cls(self) -> None:
        resp = self._make_response("not json")
        with pytest.raises(FacebookOAuthTokenError, match="non-JSON"):
            parse_json_object(resp, error_cls=FacebookOAuthTokenError, context="test endpoint")

    def test_json_array_without_error_cls_raises_valueerror(self) -> None:
        resp = self._make_response("[1, 2, 3]")
        with pytest.raises(ValueError, match="non-object JSON"):
            parse_json_object(resp, context="test endpoint")

    def test_json_array_with_error_cls_raises_error_cls(self) -> None:
        resp = self._make_response("[1, 2, 3]")
        with pytest.raises(XOAuthTokenError, match="non-object JSON"):
            parse_json_object(resp, error_cls=XOAuthTokenError, context="test endpoint")

    def test_json_string_without_error_cls_raises_valueerror(self) -> None:
        resp = self._make_response('"just a string"')
        with pytest.raises(ValueError, match="non-object JSON"):
            parse_json_object(resp, context="test endpoint")

    def test_json_number_with_error_cls_raises_error_cls(self) -> None:
        resp = self._make_response("42")
        with pytest.raises(MastodonOAuthTokenError, match="non-object JSON"):
            parse_json_object(resp, error_cls=MastodonOAuthTokenError, context="test endpoint")


class TestParseJsonObjectMessages:
    """parse_json_object error messages should be consistent and include response snippet."""

    def test_non_dict_message_consistent_with_and_without_error_cls(self) -> None:
        resp = httpx.Response(200, json=[1, 2, 3])

        # Without error_cls
        with pytest.raises(ValueError, match="non-object JSON"):
            parse_json_object(resp, context="Test endpoint")

        # With error_cls
        with pytest.raises(RuntimeError, match="non-object JSON"):
            parse_json_object(resp, error_cls=RuntimeError, context="Test endpoint")

    def test_non_json_includes_response_snippet(self) -> None:
        resp = httpx.Response(200, text="<html>Error</html>")
        with pytest.raises(ValueError, match="<html>"):
            parse_json_object(resp, context="Test endpoint")
