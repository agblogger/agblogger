"""Mastodon cross-posting implementation using Mastodon HTTP API."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from backend.crosspost.base import CrossPostContent, CrossPostResult
from backend.crosspost.http_utils import parse_json_object
from backend.crosspost.ssrf import ssrf_safe_client

logger = logging.getLogger(__name__)

MASTODON_CHAR_LIMIT = 500


def _normalize_instance_url(raw_url: str) -> str | None:
    """Return normalized Mastodon base URL when safe, otherwise None."""
    candidate = raw_url.strip().rstrip("/")
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https":
        return None
    if parsed.hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        return None

    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    port = f":{parsed_port}" if parsed_port is not None else ""
    return f"https://{parsed.hostname}{port}"


class MastodonOAuthTokenError(Exception):
    """Raised when Mastodon OAuth token exchange or verification fails."""


async def exchange_mastodon_oauth_token(
    instance_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    pkce_verifier: str,
) -> dict[str, str]:
    """Exchange authorization code for Mastodon access token and verify credentials.

    Returns dict with keys: access_token, acct, hostname.
    Raises MastodonOAuthTokenError on failure.
    """
    validated_url = _normalize_instance_url(instance_url)
    if validated_url is None:
        msg = "Invalid instance URL"
        raise MastodonOAuthTokenError(msg)

    async with ssrf_safe_client() as http_client:
        token_resp = await http_client.post(
            f"{validated_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": pkce_verifier,
            },
            timeout=15.0,
        )
        if token_resp.status_code != 200:
            msg = f"Token exchange failed: {token_resp.status_code}"
            raise MastodonOAuthTokenError(msg)
        token_data = parse_json_object(
            token_resp,
            error_cls=MastodonOAuthTokenError,
            context="Mastodon token endpoint",
        )

    access_token_value = token_data.get("access_token")
    if not isinstance(access_token_value, str) or not access_token_value:
        msg = "Token response missing access_token"
        raise MastodonOAuthTokenError(msg)
    access_token = access_token_value

    async with ssrf_safe_client() as http_client:
        verify_resp = await http_client.get(
            f"{validated_url}/api/v1/accounts/verify_credentials",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if verify_resp.status_code != 200:
            msg = "Failed to verify Mastodon credentials"
            raise MastodonOAuthTokenError(msg)
        verify_data = parse_json_object(
            verify_resp,
            error_cls=MastodonOAuthTokenError,
            context="Mastodon verify credentials endpoint",
        )

    hostname = urlparse(validated_url).hostname or ""
    acct_value = verify_data.get("acct")
    acct = acct_value if isinstance(acct_value, str) else ""
    return {
        "access_token": access_token,
        "instance_url": validated_url,
        "acct": acct,
        "hostname": hostname,
    }


def _build_status_text(content: CrossPostContent) -> str:
    """Build the status text, truncated to fit within Mastodon's character limit.

    Format: excerpt + hashtags + link.
    """
    if content.custom_text is not None:
        if len(content.custom_text) > MASTODON_CHAR_LIMIT:
            msg = f"Custom text exceeds {MASTODON_CHAR_LIMIT} character limit"
            raise ValueError(msg)
        return content.custom_text

    link = content.url
    hashtags = " ".join(f"#{label}" for label in content.labels[:10])

    suffix_parts: list[str] = []
    if hashtags:
        suffix_parts.append(hashtags)
    suffix_parts.append(link)
    suffix = "\n\n" + "\n".join(suffix_parts)

    available = MASTODON_CHAR_LIMIT - len(suffix)

    excerpt = content.excerpt
    if available <= 3:
        excerpt = excerpt[: max(available, 0)]
    elif len(excerpt) > available:
        excerpt = excerpt[: available - 3].rsplit(" ", maxsplit=1)[0] + "..."

    return excerpt + suffix


class MastodonCrossPoster:
    """Cross-poster for Mastodon-compatible instances."""

    platform: str = "mastodon"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._instance_url: str | None = None
        self._account_id: str | None = None
        self._username: str | None = None

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Mastodon using an access token.

        Expected credentials keys: access_token, instance_url.
        instance_url should be the base URL, e.g. https://mastodon.social
        """
        access_token = credentials.get("access_token", "")
        instance_url = _normalize_instance_url(credentials.get("instance_url", ""))
        if not access_token or not instance_url:
            return False

        self._access_token = access_token
        self._instance_url = instance_url

        async with ssrf_safe_client() as client:
            try:
                resp = await client.get(
                    f"{instance_url}/api/v1/accounts/verify_credentials",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    logger.warning("Mastodon auth failed: %s %s", resp.status_code, resp.text)
                    self._access_token = None
                    self._instance_url = None
                    return False
                data = parse_json_object(resp, context="Mastodon verify credentials endpoint")
                self._account_id = str(data.get("id", ""))
                acct_value = data.get("acct")
                self._username = acct_value if isinstance(acct_value, str) else ""
                return True
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Mastodon auth response parse error: %s", exc)
                self._access_token = None
                self._instance_url = None
                return False

    async def post(self, content: CrossPostContent) -> CrossPostResult:
        """Create a status on Mastodon."""
        if not self._access_token or not self._instance_url:
            return CrossPostResult(
                platform_id="",
                url="",
                success=False,
                error="Not authenticated",
            )

        status_text = _build_status_text(content)

        async with ssrf_safe_client() as client:
            try:
                resp = await client.post(
                    f"{self._instance_url}/api/v1/statuses",
                    json={"status": status_text},
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=15.0,
                )
                if resp.status_code not in (200, 201):
                    return CrossPostResult(
                        platform_id="",
                        url="",
                        success=False,
                        error=f"Mastodon API error: {resp.status_code} {resp.text}",
                    )
                data = parse_json_object(resp, context="Mastodon statuses endpoint")
                url_value = data.get("url")
                return CrossPostResult(
                    platform_id=str(data.get("id", "")),
                    url=url_value if isinstance(url_value, str) else "",
                    success=True,
                )
            except (httpx.HTTPError, ValueError) as exc:
                logger.exception("Mastodon post HTTP error")
                return CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=f"HTTP error: {exc}",
                )

    async def validate_credentials(self) -> bool:
        """Check if current access token is still valid."""
        if not self._access_token or not self._instance_url:
            return False
        async with ssrf_safe_client() as client:
            try:
                resp = await client.get(
                    f"{self._instance_url}/api/v1/accounts/verify_credentials",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=10.0,
                )
                return resp.status_code == 200
            except httpx.HTTPError:
                return False
