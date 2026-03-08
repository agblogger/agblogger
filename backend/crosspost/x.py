"""X (Twitter) cross-posting implementation using X API v2."""

from __future__ import annotations

import logging

import httpx

from backend.crosspost.base import CrossPostContent, CrossPostResult
from backend.crosspost.http_utils import get_str_field, parse_json_object, require_str_field
from backend.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

X_CHAR_LIMIT = 280


def _build_tweet_text(content: CrossPostContent) -> str:
    """Build tweet text, truncated to fit within X's character limit.

    Format: excerpt + hashtags + link.
    """
    if content.custom_text is not None:
        if len(content.custom_text) > X_CHAR_LIMIT:
            msg = f"Custom text exceeds {X_CHAR_LIMIT} character limit"
            raise ValueError(msg)
        return content.custom_text

    link = content.url
    hashtags = " ".join(f"#{label}" for label in content.labels[:5])

    suffix_parts: list[str] = []
    if hashtags:
        suffix_parts.append(hashtags)
    suffix_parts.append(link)
    suffix = "\n\n" + "\n".join(suffix_parts)

    available = X_CHAR_LIMIT - len(suffix)

    excerpt = content.excerpt
    if available <= 3:
        excerpt = ""
    elif len(excerpt) > available:
        truncated = excerpt[: available - 3].rsplit(" ", maxsplit=1)[0]
        excerpt = (truncated + "...") if truncated else ""

    return excerpt + suffix


class XOAuthTokenError(ExternalServiceError):
    """Raised when X OAuth token exchange fails."""


async def exchange_x_oauth_token(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    pkce_verifier: str,
) -> dict[str, str]:
    """Exchange authorization code for X OAuth tokens and fetch username.

    Returns dict with keys: access_token, refresh_token, username.
    Raises XOAuthTokenError on failure.
    """
    async with httpx.AsyncClient() as http_client:
        token_resp = await http_client.post(
            "https://api.x.com/2/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": pkce_verifier,
            },
            auth=(client_id, client_secret),
            timeout=15.0,
        )
        if token_resp.status_code != 200:
            body = token_resp.text[:200]
            msg = f"Token exchange failed: {token_resp.status_code} - {body}"
            raise XOAuthTokenError(msg)
        token_data = parse_json_object(
            token_resp,
            error_cls=XOAuthTokenError,
            context="X token endpoint",
        )
        access_token = require_str_field(
            token_data,
            "access_token",
            context="X token endpoint",
            error_cls=XOAuthTokenError,
        )
        refresh_token = get_str_field(token_data, "refresh_token")

        user_resp = await http_client.get(
            "https://api.x.com/2/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if user_resp.status_code != 200:
            body = user_resp.text[:200]
            msg = f"User fetch failed: {user_resp.status_code} - {body}"
            raise XOAuthTokenError(msg)
        user_data = parse_json_object(
            user_resp,
            error_cls=XOAuthTokenError,
            context="X user profile endpoint",
        )
        data_obj = user_data.get("data")
        if not isinstance(data_obj, dict) or "username" not in data_obj:
            msg = "User profile response missing username"
            raise XOAuthTokenError(msg)
        username = require_str_field(
            data_obj,
            "username",
            context="X user profile endpoint",
            error_cls=XOAuthTokenError,
        )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "username": username,
    }


class XCrossPoster:
    """Cross-poster for X (Twitter) using API v2."""

    platform: str = "x"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._username: str | None = None
        self._client_id: str = ""
        self._client_secret: str = ""
        self._updated_credentials: dict[str, str] | None = None

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Authenticate with X using OAuth 2.0 tokens."""
        access_token = credentials.get("access_token", "")
        if not access_token:
            return False

        self._access_token = access_token
        self._refresh_token = credentials.get("refresh_token", "")
        self._username = credentials.get("username", "")
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    "https://api.x.com/2/users/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    logger.warning("X auth failed: %s %s", resp.status_code, resp.text)
                    self._access_token = None
                    return False
                data = parse_json_object(resp, context="X user profile endpoint")
                data_obj = data.get("data")
                if isinstance(data_obj, dict):
                    username = data_obj.get("username")
                    if isinstance(username, str):
                        self._username = username
                return True
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("X auth response parse error: %s", exc)
                self._access_token = None
                return False

    async def _try_refresh_token(self) -> bool:
        """Attempt to refresh the access token."""
        if not self._refresh_token or not self._client_id:
            return False

        async with httpx.AsyncClient() as client:
            try:
                data: dict[str, str] = {
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                }
                resp = await client.post(
                    "https://api.x.com/2/oauth2/token",
                    data=data,
                    auth=(self._client_id, self._client_secret),
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    logger.warning("X refresh request failed with status %s", resp.status_code)
                    return False
                token_data = parse_json_object(resp, context="X token refresh endpoint")
                try:
                    new_access_token = require_str_field(
                        token_data,
                        "access_token",
                        context="X token refresh endpoint",
                    )
                except ValueError:
                    logger.warning("X refresh response missing expected field")
                    return False
                self._access_token = new_access_token
                refresh_token_value = token_data.get("refresh_token", self._refresh_token)
                if isinstance(refresh_token_value, str):
                    self._refresh_token = refresh_token_value
                self._updated_credentials = {
                    "access_token": self._access_token or "",
                    "refresh_token": self._refresh_token or "",
                    "username": self._username or "",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                }
                return True
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("X OAuth refresh error: %s", exc)
                return False

    async def post(self, content: CrossPostContent) -> CrossPostResult:
        """Create a tweet on X."""
        if not self._access_token:
            return CrossPostResult(
                platform_id="",
                url="",
                success=False,
                error="Not authenticated",
            )

        tweet_text = _build_tweet_text(content)

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    "https://api.x.com/2/tweets",
                    json={"text": tweet_text},
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=15.0,
                )
                if resp.status_code == 401 and await self._try_refresh_token():
                    resp = await client.post(
                        "https://api.x.com/2/tweets",
                        json={"text": tweet_text},
                        headers={"Authorization": f"Bearer {self._access_token}"},
                        timeout=15.0,
                    )
                if resp.status_code not in (200, 201):
                    return CrossPostResult(
                        platform_id="",
                        url="",
                        success=False,
                        error=f"X API error: {resp.status_code} {resp.text}",
                    )
                data = parse_json_object(resp, context="X tweets endpoint")
                tweet_id = ""
                data_obj = data.get("data")
                if isinstance(data_obj, dict):
                    id_value = data_obj.get("id")
                    if isinstance(id_value, str):
                        tweet_id = id_value
                tweet_url = f"https://x.com/{self._username}/status/{tweet_id}" if tweet_id else ""
                return CrossPostResult(platform_id=tweet_id, url=tweet_url, success=True)
            except (httpx.HTTPError, ValueError) as exc:
                logger.exception("X post HTTP error")
                return CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=f"HTTP error: {exc}",
                )

    async def validate_credentials(self) -> bool:
        """Check if current access token is still valid."""
        if not self._access_token:
            return False
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    "https://api.x.com/2/users/me",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=10.0,
                )
                return resp.status_code == 200
            except httpx.HTTPError as exc:
                logger.warning("X account validation failed: %s: %s", type(exc).__name__, exc)
                return False

    def get_updated_credentials(self) -> dict[str, str] | None:
        """Return refreshed credentials if tokens were updated."""
        return self._updated_credentials
