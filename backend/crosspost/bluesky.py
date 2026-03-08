"""Bluesky cross-posting implementation using AT Protocol OAuth + DPoP."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import grapheme
import httpx
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

from backend.crosspost.atproto_oauth import create_dpop_proof
from backend.crosspost.base import CrossPostContent, CrossPostResult
from backend.crosspost.http_utils import get_str_field, parse_json_object
from backend.crosspost.ssrf import ssrf_safe_client

logger = logging.getLogger(__name__)

BSKY_CHAR_LIMIT = 300

REQUIRED_CREDENTIAL_FIELDS = frozenset(
    {
        "access_token",
        "did",
        "handle",
        "pds_url",
        "dpop_private_key_pem",
        "dpop_jwk",
        "dpop_nonce",
        "auth_server_issuer",
        "token_endpoint",
        "refresh_token",
        "client_id",
    }
)


@dataclass
class _AuthState:
    """Authenticated state for a Bluesky OAuth session."""

    access_token: str
    did: str
    handle: str
    pds_url: str
    dpop_private_key: EllipticCurvePrivateKey
    dpop_jwk: dict[str, str]
    dpop_nonce: str
    auth_server_issuer: str
    token_endpoint: str
    refresh_token: str
    client_id: str


def _build_post_text(content: CrossPostContent) -> str:
    """Build the post text, truncated to fit within Bluesky's character limit.

    Format: excerpt + hashtags + link.
    The link is always included at the end.
    """
    if content.custom_text is not None:
        if grapheme.length(content.custom_text) > BSKY_CHAR_LIMIT:
            msg = f"Custom text exceeds {BSKY_CHAR_LIMIT} character limit"
            raise ValueError(msg)
        return content.custom_text

    link = content.url
    hashtags = " ".join(f"#{label}" for label in content.labels[:5])

    # Reserve space for link and hashtags
    suffix_parts: list[str] = []
    if hashtags:
        suffix_parts.append(hashtags)
    suffix_parts.append(link)
    suffix = "\n\n" + "\n".join(suffix_parts)

    available = BSKY_CHAR_LIMIT - grapheme.length(suffix)

    excerpt = content.excerpt
    if available <= 3:
        excerpt = grapheme.slice(excerpt, 0, max(available, 0))
    elif grapheme.length(excerpt) > available:
        truncated = grapheme.slice(excerpt, 0, available - 3)
        # Try to break at a word boundary
        space_pos = truncated.rfind(" ")
        if space_pos > 0:
            truncated = truncated[:space_pos]
        excerpt = truncated + "..."

    return excerpt + suffix


def _find_facets(text: str, content: CrossPostContent) -> list[dict[str, Any]]:
    """Build rich text facets for links and hashtags."""
    facets: list[dict[str, Any]] = []

    # Link facet for the URL
    url = content.url
    url_start = text.find(url)
    if url_start >= 0:
        byte_start = len(text[:url_start].encode("utf-8"))
        byte_end = byte_start + len(url.encode("utf-8"))
        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [
                    {
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": url,
                    }
                ],
            }
        )

    # Hashtag facets (rfind to match tags in suffix, not in excerpt)
    for label in content.labels[:5]:
        tag_text = f"#{label}"
        tag_start = text.rfind(tag_text)
        if tag_start >= 0:
            byte_start = len(text[:tag_start].encode("utf-8"))
            byte_end = byte_start + len(tag_text.encode("utf-8"))
            facets.append(
                {
                    "index": {"byteStart": byte_start, "byteEnd": byte_end},
                    "features": [
                        {
                            "$type": "app.bsky.richtext.facet#tag",
                            "tag": label,
                        }
                    ],
                }
            )

    return facets


class BlueskyCrossPoster:
    """Cross-poster for Bluesky via AT Protocol OAuth + DPoP."""

    platform: str = "bluesky"

    def __init__(self) -> None:
        self._auth: _AuthState | None = None
        self._updated_credentials: dict[str, str] | None = None

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Load OAuth credentials. No network call needed."""
        if not REQUIRED_CREDENTIAL_FIELDS.issubset(credentials):
            return False
        pds_url = credentials["pds_url"].rstrip("/")
        try:
            key = load_pem_private_key(
                credentials["dpop_private_key_pem"].encode(),
                password=None,
            )
        except (ValueError, TypeError, UnsupportedAlgorithm):  # fmt: skip
            return False
        if not isinstance(key, EllipticCurvePrivateKey):
            return False
        try:
            dpop_jwk = json.loads(credentials["dpop_jwk"])
        except (json.JSONDecodeError, TypeError):  # fmt: skip
            return False
        self._auth = _AuthState(
            access_token=credentials["access_token"],
            did=credentials["did"],
            handle=credentials["handle"],
            pds_url=pds_url,
            dpop_private_key=key,
            dpop_jwk=dpop_jwk,
            dpop_nonce=credentials["dpop_nonce"],
            auth_server_issuer=credentials["auth_server_issuer"],
            token_endpoint=credentials["token_endpoint"],
            refresh_token=credentials["refresh_token"],
            client_id=credentials["client_id"],
        )
        return True

    def get_updated_credentials(self) -> dict[str, str] | None:
        """Return updated credentials if tokens were refreshed during post()."""
        return self._updated_credentials

    async def _make_pds_request(
        self,
        method: str,
        url: str,
        auth: _AuthState,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an authenticated request to the PDS with DPoP."""
        dpop = create_dpop_proof(
            method=method,
            url=url,
            key=auth.dpop_private_key,
            jwk=auth.dpop_jwk,
            nonce=auth.dpop_nonce,
            access_token=auth.access_token,
        )
        headers = {
            "Authorization": f"DPoP {auth.access_token}",
            "DPoP": dpop,
        }
        async with ssrf_safe_client() as client:
            if method == "POST":
                resp = await client.post(url, json=json_body, headers=headers, timeout=15.0)
            else:
                resp = await client.get(url, headers=headers, timeout=15.0)

        new_nonce = resp.headers.get("DPoP-Nonce")
        if new_nonce:
            auth.dpop_nonce = new_nonce
        return resp

    async def _try_refresh_tokens(self, auth: _AuthState) -> bool:
        """Attempt to refresh the access token."""
        from backend.crosspost.atproto_oauth import ATProtoOAuthError, refresh_access_token

        try:
            result = await refresh_access_token(
                token_endpoint=auth.token_endpoint,
                auth_server_issuer=auth.auth_server_issuer,
                refresh_token=auth.refresh_token,
                client_id=auth.client_id,
                private_key=auth.dpop_private_key,
                jwk=auth.dpop_jwk,
                dpop_nonce=auth.dpop_nonce,
            )
            auth.access_token = result["access_token"]
            auth.refresh_token = result.get("refresh_token") or auth.refresh_token
            auth.dpop_nonce = result.get("dpop_nonce") or auth.dpop_nonce
            self._updated_credentials = {
                "access_token": auth.access_token,
                "refresh_token": auth.refresh_token,
                "did": auth.did,
                "handle": auth.handle,
                "pds_url": auth.pds_url,
                "dpop_private_key_pem": auth.dpop_private_key.private_bytes(
                    Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
                ).decode(),
                "dpop_jwk": json.dumps(auth.dpop_jwk),
                "dpop_nonce": auth.dpop_nonce,
                "auth_server_issuer": auth.auth_server_issuer,
                "token_endpoint": auth.token_endpoint,
                "client_id": auth.client_id,
            }
            return True
        except ATProtoOAuthError:
            logger.exception("Token refresh failed")
            return False

    async def post(self, content: CrossPostContent) -> CrossPostResult:
        """Create a post on Bluesky using DPoP-bound OAuth tokens."""
        auth = self._auth
        if auth is None:
            return CrossPostResult(
                platform_id="",
                url="",
                success=False,
                error="Not authenticated",
            )

        text = _build_post_text(content)
        facets = _find_facets(text, content)

        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        if facets:
            record["facets"] = facets

        payload = {
            "repo": auth.did,
            "collection": "app.bsky.feed.post",
            "record": record,
        }

        url = f"{auth.pds_url}/xrpc/com.atproto.repo.createRecord"
        try:
            resp = await self._make_pds_request("POST", url, auth, json_body=payload)

            if resp.status_code == 401 and auth.refresh_token:
                refreshed = await self._try_refresh_tokens(auth)
                if refreshed:
                    resp = await self._make_pds_request("POST", url, auth, json_body=payload)

            if resp.status_code != 200:
                return CrossPostResult(
                    platform_id="",
                    url="",
                    success=False,
                    error=f"Bluesky API error: {resp.status_code} {resp.text}",
                )
            data = parse_json_object(resp, context="Bluesky createRecord endpoint")
            uri = get_str_field(data, "uri")
            rkey = uri.split("/")[-1]
            post_url = f"https://bsky.app/profile/{auth.handle}/post/{rkey}" if rkey else ""
            return CrossPostResult(
                platform_id=uri,
                url=post_url,
                success=True,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("Bluesky post HTTP error")
            return CrossPostResult(
                platform_id="",
                url="",
                success=False,
                error=f"HTTP error: {exc}",
            )

    async def validate_credentials(self) -> bool:
        """Check if current session is still valid via DPoP-bound request."""
        auth = self._auth
        if auth is None:
            return False
        try:
            url = f"{auth.pds_url}/xrpc/com.atproto.server.getSession"
            resp = await self._make_pds_request("GET", url, auth)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
