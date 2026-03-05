"""Facebook cross-posting implementation using Graph API v22.0."""

from __future__ import annotations

import logging

import httpx

from backend.crosspost.base import CrossPostContent, CrossPostResult
from backend.crosspost.http_utils import parse_json_object
from backend.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

FACEBOOK_GRAPH_API = "https://graph.facebook.com/v22.0"


class FacebookOAuthTokenError(ExternalServiceError):
    """Raised when Facebook OAuth token exchange fails."""


def _build_facebook_text(content: CrossPostContent) -> str:
    """Build post text for Facebook. No character limit enforced."""
    if content.custom_text is not None:
        return content.custom_text

    hashtags = " ".join(f"#{label}" for label in content.labels[:10])

    parts: list[str] = [content.excerpt]
    if hashtags:
        parts.append(hashtags)
    return "\n\n".join(parts)


async def exchange_facebook_oauth_token(
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> dict[str, object]:
    """Exchange authorization code for a Facebook user access token.

    Then exchange for a long-lived token and fetch managed pages.
    Returns dict with keys: user_access_token, pages (list of dicts).
    Raises FacebookOAuthTokenError on failure.
    """
    async with httpx.AsyncClient() as http_client:
        # Exchange code for short-lived user token
        token_resp = await http_client.post(
            f"{FACEBOOK_GRAPH_API}/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=15.0,
        )
        if token_resp.status_code != 200:
            body = token_resp.text[:200]
            msg = f"Token exchange failed: {token_resp.status_code} - {body}"
            raise FacebookOAuthTokenError(msg)
        token_data = parse_json_object(
            token_resp,
            error_cls=FacebookOAuthTokenError,
            context="Facebook token endpoint",
        )
        short_token_value = token_data.get("access_token")
        if not isinstance(short_token_value, str) or not short_token_value:
            msg = "Token response missing access_token"
            raise FacebookOAuthTokenError(msg)
        short_token = short_token_value

        # Exchange for long-lived user token
        ll_resp = await http_client.post(
            f"{FACEBOOK_GRAPH_API}/oauth/access_token",
            data={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
            timeout=15.0,
        )
        if ll_resp.status_code != 200:
            body = ll_resp.text[:200]
            msg = f"Long-lived token exchange failed: {ll_resp.status_code} - {body}"
            raise FacebookOAuthTokenError(msg)
        ll_data = parse_json_object(
            ll_resp,
            error_cls=FacebookOAuthTokenError,
            context="Facebook long-lived token endpoint",
        )
        long_lived_token_value = ll_data.get("access_token")
        if not isinstance(long_lived_token_value, str) or not long_lived_token_value:
            msg = "Long-lived token response missing access_token"
            raise FacebookOAuthTokenError(msg)
        long_lived_token = long_lived_token_value

        # Fetch managed pages
        pages_resp = await http_client.get(
            f"{FACEBOOK_GRAPH_API}/me/accounts",
            headers={"Authorization": f"Bearer {long_lived_token}"},
            timeout=15.0,
        )
        if pages_resp.status_code != 200:
            body = pages_resp.text[:200]
            msg = f"Failed to fetch pages: {pages_resp.status_code} - {body}"
            raise FacebookOAuthTokenError(msg)
        pages_data = parse_json_object(
            pages_resp,
            error_cls=FacebookOAuthTokenError,
            context="Facebook pages endpoint",
        )
        pages_value = pages_data.get("data", [])
        if not isinstance(pages_value, list) or not pages_value:
            msg = "No Facebook Pages found. You must manage at least one Page."
            raise FacebookOAuthTokenError(msg)

    return {
        "user_access_token": long_lived_token,
        "pages": pages_value,
    }


class FacebookCrossPoster:
    """Cross-poster for Facebook Pages using Graph API."""

    platform: str = "facebook"

    def __init__(self) -> None:
        self._page_access_token: str | None = None
        self._page_id: str | None = None
        self._page_name: str | None = None

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Facebook Page credentials.

        Expected keys: page_access_token, page_id, page_name.
        Validates the token by calling the Graph API.
        """
        page_access_token = credentials.get("page_access_token", "")
        page_id = credentials.get("page_id", "")
        if not page_access_token or not page_id:
            return False

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{FACEBOOK_GRAPH_API}/{page_id}",
                    headers={"Authorization": f"Bearer {page_access_token}"},
                    params={"fields": "id,name"},
                    timeout=10.0,
                )
                if resp.status_code != 200:
                    logger.warning("Facebook auth failed: %s %s", resp.status_code, resp.text)
                    return False
            except httpx.HTTPError as exc:
                logger.warning("Facebook auth failed: %s: %s", type(exc).__name__, exc)
                return False

        self._page_access_token = page_access_token
        self._page_id = page_id
        self._page_name = credentials.get("page_name", "")
        return True

    async def post(self, content: CrossPostContent) -> CrossPostResult:
        """Create a post on a Facebook Page."""
        if not self._page_access_token or not self._page_id:
            return CrossPostResult(platform_id="", url="", success=False, error="Not authenticated")

        message = _build_facebook_text(content)

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{FACEBOOK_GRAPH_API}/{self._page_id}/feed",
                    json={
                        "message": message,
                        "link": content.url,
                    },
                    headers={"Authorization": f"Bearer {self._page_access_token}"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    return CrossPostResult(
                        platform_id="",
                        url="",
                        success=False,
                        error=f"Facebook API error: {resp.status_code} {resp.text}",
                    )
                data = parse_json_object(resp, context="Facebook feed endpoint")
                post_id_value = data.get("id")
                post_id = post_id_value if isinstance(post_id_value, str) else ""
                post_url = f"https://www.facebook.com/{post_id}" if post_id else ""
                return CrossPostResult(platform_id=post_id, url=post_url, success=True)
            except (httpx.HTTPError, ValueError) as exc:
                logger.exception("Facebook post HTTP error")
                return CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=f"HTTP error: {exc}",
                )

    async def validate_credentials(self) -> bool:
        """Check if the Page access token is still valid."""
        if not self._page_access_token:
            return False
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{FACEBOOK_GRAPH_API}/me",
                    headers={"Authorization": f"Bearer {self._page_access_token}"},
                    timeout=10.0,
                )
                return resp.status_code == 200
            except httpx.HTTPError as exc:
                logger.warning(
                    "Facebook account validation failed: %s: %s", type(exc).__name__, exc
                )
                return False
