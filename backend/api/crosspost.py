"""Cross-posting API endpoints."""

from __future__ import annotations

import base64
import hashlib
import json as json_mod
import logging
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_content_manager,
    get_session,
    get_settings,
    require_auth,
)
from backend.config import Settings
from backend.exceptions import PostNotFoundError
from backend.filesystem.content_manager import ContentManager
from backend.models.user import User
from backend.schemas.crosspost import (
    BlueskyAuthorizeRequest,
    BlueskyAuthorizeResponse,
    CrossPostHistoryResponse,
    CrossPostRequest,
    CrossPostResponse,
    CrossPostStatus,
    FacebookAuthorizeResponse,
    FacebookPagesResponse,
    FacebookSelectPageRequest,
    FacebookSelectPageResponse,
    MastodonAuthorizeRequest,
    MastodonAuthorizeResponse,
    SocialAccountCreate,
    SocialAccountResponse,
    XAuthorizeResponse,
)
from backend.services.crosspost_service import (
    DuplicateAccountError,
    create_social_account,
    crosspost,
    delete_social_account,
    get_crosspost_history,
    get_social_accounts,
)

logger = logging.getLogger(__name__)


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and S256 code challenge."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    code_verifier = "".join(secrets.choice(unreserved) for _ in range(64))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


async def _upsert_social_account(
    session: AsyncSession,
    user_id: int,
    account_data: SocialAccountCreate,
    secret_key: str,
    platform: str,
    account_name: str,
) -> None:
    """Create a social account, replacing an existing one with the same platform+name."""
    try:
        await create_social_account(session, user_id, account_data, secret_key)
    except DuplicateAccountError:
        existing = await get_social_accounts(session, user_id)
        replaced = False
        for acct in existing:
            if acct.platform == platform and acct.account_name == account_name:
                await delete_social_account(session, acct.id, user_id)
                replaced = True
                break
        if not replaced:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{platform.capitalize()} account already exists",
            ) from None
        await create_social_account(session, user_id, account_data, secret_key)


router = APIRouter(prefix="/api/crosspost", tags=["crosspost"])


@router.post("/accounts", response_model=SocialAccountResponse, status_code=201)
async def create_account_endpoint(
    body: SocialAccountCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
) -> SocialAccountResponse:
    """Connect a social media account for cross-posting."""
    try:
        account = await create_social_account(session, user.id, body, settings.secret_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return SocialAccountResponse(
        id=account.id,
        platform=account.platform,
        account_name=account.account_name,
        created_at=account.created_at,
    )


@router.get("/accounts", response_model=list[SocialAccountResponse])
async def list_accounts_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> list[SocialAccountResponse]:
    """List connected social accounts."""
    accounts = await get_social_accounts(session, user.id)
    return [
        SocialAccountResponse(
            id=acct.id,
            platform=acct.platform,
            account_name=acct.account_name,
            created_at=acct.created_at,
        )
        for acct in accounts
    ]


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account_endpoint(
    account_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> None:
    """Delete a connected social account."""
    deleted = await delete_social_account(session, account_id, user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Social account not found",
        )


@router.post("/post", response_model=list[CrossPostResponse])
async def crosspost_endpoint(
    body: CrossPostRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
) -> list[CrossPostResponse]:
    """Cross-post a blog post to selected platforms."""
    # Build site URL from settings
    site_url = f"http{'s' if not settings.debug else ''}://{settings.host}"
    if settings.port not in (80, 443):
        site_url += f":{settings.port}"

    try:
        results = await crosspost(
            session,
            content_manager,
            body.post_path,
            body.platforms,
            user,
            site_url,
            secret_key=settings.secret_key,
            custom_text=body.custom_text,
        )
    except PostNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        CrossPostResponse(
            id=0,  # IDs not needed in response
            post_path=body.post_path,
            platform=body.platforms[i],
            platform_id=r.platform_id or None,
            status=CrossPostStatus.POSTED if r.success else CrossPostStatus.FAILED,
            posted_at=None,
            error=r.error,
        )
        for i, r in enumerate(results)
    ]


@router.get("/history/{post_path:path}", response_model=CrossPostHistoryResponse)
async def history_endpoint(
    post_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_auth)],
) -> CrossPostHistoryResponse:
    """Get cross-posting history for a blog post."""
    records = await get_crosspost_history(session, post_path, user.id)
    return CrossPostHistoryResponse(
        items=[
            CrossPostResponse(
                id=cp.id,
                post_path=cp.post_path,
                platform=cp.platform,
                platform_id=cp.platform_id,
                status=CrossPostStatus(cp.status),
                posted_at=cp.posted_at,
                error=cp.error,
            )
            for cp in records
        ]
    )


@router.get("/bluesky/client-metadata.json")
async def bluesky_client_metadata(
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> dict[str, object]:
    """Serve AT Protocol OAuth client metadata document."""
    if not settings.bluesky_client_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bluesky OAuth not configured: BLUESKY_CLIENT_URL not set",
        )
    base_url = settings.bluesky_client_url.rstrip("/")
    client_id = f"{base_url}/api/crosspost/bluesky/client-metadata.json"
    redirect_uri = f"{base_url}/api/crosspost/bluesky/callback"
    jwk = request.app.state.atproto_oauth_jwk
    return {
        "client_id": client_id,
        "client_name": "AgBlogger",
        "client_uri": base_url,
        "grant_types": ["authorization_code", "refresh_token"],
        "scope": "atproto transition:generic",
        "response_types": ["code"],
        "redirect_uris": [redirect_uri],
        "dpop_bound_access_tokens": True,
        "application_type": "web",
        "token_endpoint_auth_method": "private_key_jwt",
        "token_endpoint_auth_signing_alg": "ES256",
        "jwks": {"keys": [jwk]},
    }


@router.post("/bluesky/authorize", response_model=BlueskyAuthorizeResponse)
async def bluesky_authorize(
    body: BlueskyAuthorizeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> BlueskyAuthorizeResponse:
    """Start Bluesky OAuth flow: resolve handle, send PAR, return auth URL."""
    if not settings.bluesky_client_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bluesky OAuth not configured: BLUESKY_CLIENT_URL not set",
        )
    from backend.crosspost.atproto_oauth import (
        ATProtoOAuthError,
        discover_auth_server,
        resolve_handle_to_did,
        send_par_request,
    )

    base_url = settings.bluesky_client_url.rstrip("/")
    client_id = f"{base_url}/api/crosspost/bluesky/client-metadata.json"
    redirect_uri = f"{base_url}/api/crosspost/bluesky/callback"
    try:
        did = await resolve_handle_to_did(body.handle)
        auth_meta = await discover_auth_server(did)
        par_result = await send_par_request(
            auth_server_meta=auth_meta,
            client_id=client_id,
            redirect_uri=redirect_uri,
            did=did,
            scope="atproto transition:generic",
            private_key=request.app.state.atproto_oauth_key,
            jwk=request.app.state.atproto_oauth_jwk,
        )
    except ATProtoOAuthError as exc:
        logger.error("Bluesky OAuth error during authorize: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bluesky authentication failed",
        ) from exc
    state_store = request.app.state.bluesky_oauth_state
    state_store.set(
        par_result["state"],
        {
            "pkce_verifier": par_result["pkce_verifier"],
            "dpop_nonce": par_result["dpop_nonce"],
            "user_id": user.id,
            "did": did,
            "handle": body.handle,
            "auth_server_meta": auth_meta,
        },
    )
    return BlueskyAuthorizeResponse(authorization_url=par_result["authorization_url"])


@router.get("/bluesky/callback")
async def bluesky_callback(
    request: Request,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    iss: Annotated[str, Query()] = "",
) -> RedirectResponse:
    """Handle Bluesky OAuth callback: exchange code for tokens, store account."""
    state_store = request.app.state.bluesky_oauth_state
    pending = state_store.pop(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )
    expected_issuer = pending["auth_server_meta"]["issuer"]
    if iss and iss != expected_issuer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Issuer mismatch in OAuth callback",
        )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    from backend.crosspost.atproto_oauth import (
        ATProtoOAuthError,
        exchange_code_for_tokens,
    )

    base_url = settings.bluesky_client_url.rstrip("/")
    client_id = f"{base_url}/api/crosspost/bluesky/client-metadata.json"
    redirect_uri = f"{base_url}/api/crosspost/bluesky/callback"
    auth_meta = pending["auth_server_meta"]
    private_key = request.app.state.atproto_oauth_key
    jwk = request.app.state.atproto_oauth_jwk
    try:
        token_data = await exchange_code_for_tokens(
            token_endpoint=auth_meta["token_endpoint"],
            auth_server_issuer=auth_meta["issuer"],
            code=code,
            redirect_uri=redirect_uri,
            pkce_verifier=pending["pkce_verifier"],
            client_id=client_id,
            private_key=private_key,
            jwk=jwk,
            dpop_nonce=pending["dpop_nonce"],
        )
    except ATProtoOAuthError as exc:
        logger.error("Bluesky OAuth callback error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bluesky token exchange failed",
        ) from exc
    if token_data.get("sub") != pending["did"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DID mismatch in token response",
        )
    # Validate required token response fields
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bluesky token response missing access_token",
        )
    # The DPoP key used for PDS requests must match the key used during token
    # exchange, because the access token is DPoP-bound to that key.
    dpop_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    credentials = {
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "did": pending["did"],
        "handle": pending["handle"],
        "pds_url": auth_meta["pds_url"],
        "dpop_private_key_pem": dpop_pem,
        "dpop_jwk": json_mod.dumps(jwk),
        "dpop_nonce": token_data.get("dpop_nonce", ""),
        "auth_server_issuer": auth_meta["issuer"],
        "token_endpoint": auth_meta["token_endpoint"],
        "client_id": client_id,
    }
    account_data = SocialAccountCreate(
        platform="bluesky",
        account_name=pending["handle"],
        credentials=credentials,
    )
    await _upsert_social_account(
        session,
        pending["user_id"],
        account_data,
        settings.secret_key,
        "bluesky",
        pending["handle"],
    )
    return RedirectResponse(url=f"{base_url}/admin", status_code=303)


@router.post("/mastodon/authorize", response_model=MastodonAuthorizeResponse)
async def mastodon_authorize(
    body: MastodonAuthorizeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> MastodonAuthorizeResponse:
    """Start Mastodon OAuth flow: register app dynamically, return auth URL."""
    if not settings.bluesky_client_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth not configured: BLUESKY_CLIENT_URL not set",
        )
    from backend.crosspost.mastodon import _normalize_instance_url

    instance_url = _normalize_instance_url(body.instance_url)
    if instance_url is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid instance URL",
        )

    base_url = settings.bluesky_client_url.rstrip("/")
    redirect_uri = f"{base_url}/api/crosspost/mastodon/callback"

    code_verifier, code_challenge = _generate_pkce_pair()
    oauth_state = secrets.token_hex(32)

    import httpx

    from backend.crosspost.ssrf import ssrf_safe_client

    try:
        async with ssrf_safe_client() as http_client:
            reg_resp = await http_client.post(
                f"{instance_url}/api/v1/apps",
                data={
                    "client_name": "AgBlogger",
                    "redirect_uris": redirect_uri,
                    "scopes": "read:accounts write:statuses",
                    "website": base_url,
                },
                timeout=15.0,
            )
            if reg_resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"App registration failed: {reg_resp.status_code}",
                )
            try:
                reg_data = reg_resp.json()
            except ValueError as json_exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Mastodon app registration returned non-JSON response",
                ) from json_exc
    except httpx.HTTPError as exc:
        logger.error("Mastodon connection error during authorize: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to Mastodon instance",
        ) from exc

    client_id = reg_data.get("client_id")
    client_secret = reg_data.get("client_secret")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mastodon app registration response missing client credentials",
        )

    # Store pending state
    state_store = request.app.state.mastodon_oauth_state
    state_store.set(
        oauth_state,
        {
            "instance_url": instance_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "pkce_verifier": code_verifier,
            "user_id": user.id,
            "redirect_uri": redirect_uri,
        },
    )

    auth_params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read:accounts write:statuses",
            "state": oauth_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    authorization_url = f"{instance_url}/oauth/authorize?{auth_params}"

    return MastodonAuthorizeResponse(authorization_url=authorization_url)


@router.get("/mastodon/callback")
async def mastodon_callback(
    request: Request,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Handle Mastodon OAuth callback: exchange code for token, store account."""
    state_store = request.app.state.mastodon_oauth_state
    pending = state_store.pop(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    redirect_uri: str = pending["redirect_uri"]

    # Exchange code for token and verify credentials via mastodon module
    # (moved to module function for SSRF-safe URL validation)
    import httpx

    from backend.crosspost.mastodon import MastodonOAuthTokenError, exchange_mastodon_oauth_token

    try:
        token_result = await exchange_mastodon_oauth_token(
            instance_url=pending["instance_url"],
            code=code,
            client_id=pending["client_id"],
            client_secret=pending["client_secret"],
            redirect_uri=redirect_uri,
            pkce_verifier=pending["pkce_verifier"],
        )
    except MastodonOAuthTokenError as exc:
        logger.error("Mastodon OAuth callback error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mastodon token exchange failed",
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("Mastodon OAuth HTTP error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mastodon authentication failed",
        ) from exc

    mastodon_access_token = token_result.get("access_token")
    if not mastodon_access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mastodon token exchange returned no access token",
        )
    acct = token_result.get("acct", "")
    hostname = token_result.get("hostname", "")
    if not acct or not hostname:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mastodon token exchange returned incomplete account info",
        )
    account_name = f"@{acct}@{hostname}"
    credentials = {
        "access_token": mastodon_access_token,
        "instance_url": token_result.get("instance_url", ""),
    }
    account_data = SocialAccountCreate(
        platform="mastodon",
        account_name=account_name,
        credentials=credentials,
    )
    await _upsert_social_account(
        session,
        pending["user_id"],
        account_data,
        settings.secret_key,
        "mastodon",
        account_name,
    )

    base_url = settings.bluesky_client_url.rstrip("/")
    return RedirectResponse(url=f"{base_url}/admin", status_code=303)


@router.post("/x/authorize", response_model=XAuthorizeResponse)
async def x_authorize(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> XAuthorizeResponse:
    """Start X (Twitter) OAuth 2.0 flow with PKCE."""
    if not settings.x_client_id or not settings.x_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="X OAuth not configured: X_CLIENT_ID and X_CLIENT_SECRET not set",
        )
    if not settings.bluesky_client_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth not configured: BLUESKY_CLIENT_URL not set",
        )

    base_url = settings.bluesky_client_url.rstrip("/")
    redirect_uri = f"{base_url}/api/crosspost/x/callback"

    code_verifier, code_challenge = _generate_pkce_pair()
    oauth_state = secrets.token_hex(32)

    state_store = request.app.state.x_oauth_state
    state_store.set(
        oauth_state,
        {
            "pkce_verifier": code_verifier,
            "user_id": user.id,
            "redirect_uri": redirect_uri,
            "client_id": settings.x_client_id,
            "client_secret": settings.x_client_secret,
        },
    )

    auth_params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.x_client_id,
            "redirect_uri": redirect_uri,
            "scope": "tweet.read tweet.write users.read offline.access",
            "state": oauth_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    authorization_url = f"https://x.com/i/oauth2/authorize?{auth_params}"
    return XAuthorizeResponse(authorization_url=authorization_url)


@router.get("/x/callback")
async def x_callback(
    request: Request,
    state: Annotated[str, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Handle X OAuth callback: exchange code for tokens, store account."""
    base_url = (settings.bluesky_client_url or "").rstrip("/")

    if error is not None:
        logger.warning("X OAuth error: %s", error)
        error_params = urlencode({"oauth_error": error})
        return RedirectResponse(url=f"{base_url}/admin?{error_params}", status_code=303)

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    state_store = request.app.state.x_oauth_state
    pending = state_store.pop(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    import httpx

    from backend.crosspost.x import XOAuthTokenError, exchange_x_oauth_token

    try:
        token_result = await exchange_x_oauth_token(
            code=code,
            client_id=pending["client_id"],
            client_secret=pending["client_secret"],
            redirect_uri=pending["redirect_uri"],
            pkce_verifier=pending["pkce_verifier"],
        )
    except XOAuthTokenError as exc:
        logger.error("X OAuth callback error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="X token exchange failed",
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("X OAuth HTTP error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="X authentication failed",
        ) from exc

    x_access_token = token_result.get("access_token")
    x_refresh_token = token_result.get("refresh_token")
    username = token_result.get("username")
    if not x_access_token or not x_refresh_token or not username:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="X token exchange returned incomplete data",
        )

    credentials = {
        "access_token": x_access_token,
        "refresh_token": x_refresh_token,
        "username": username,
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
    }
    account_name = f"@{username}"
    account_data = SocialAccountCreate(
        platform="x",
        account_name=account_name,
        credentials=credentials,
    )
    await _upsert_social_account(
        session,
        pending["user_id"],
        account_data,
        settings.secret_key,
        "x",
        account_name,
    )

    return RedirectResponse(url=f"{base_url}/admin", status_code=303)


@router.post("/facebook/authorize", response_model=FacebookAuthorizeResponse)
async def facebook_authorize(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> FacebookAuthorizeResponse:
    """Start Facebook OAuth flow."""
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Facebook OAuth not configured: FACEBOOK_APP_ID and FACEBOOK_APP_SECRET not set"
            ),
        )
    if not settings.bluesky_client_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth not configured: BLUESKY_CLIENT_URL not set",
        )

    base_url = settings.bluesky_client_url.rstrip("/")
    redirect_uri = f"{base_url}/api/crosspost/facebook/callback"
    oauth_state = secrets.token_hex(32)

    state_store = request.app.state.facebook_oauth_state
    state_store.set(
        oauth_state,
        {
            "user_id": user.id,
            "redirect_uri": redirect_uri,
            "app_id": settings.facebook_app_id,
            "app_secret": settings.facebook_app_secret,
        },
    )

    auth_params = urlencode(
        {
            "client_id": settings.facebook_app_id,
            "redirect_uri": redirect_uri,
            "state": oauth_state,
            "scope": ("pages_manage_posts,pages_read_engagement,pages_show_list"),
            "response_type": "code",
        }
    )
    authorization_url = f"https://www.facebook.com/v22.0/dialog/oauth?{auth_params}"
    return FacebookAuthorizeResponse(authorization_url=authorization_url)


@router.get("/facebook/callback")
async def facebook_callback(
    request: Request,
    state: Annotated[str, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Handle Facebook OAuth callback.

    Exchanges authorization code for tokens, fetches managed pages.
    Auto-selects if there is only one page; otherwise stores pages
    for selection via the select-page endpoint.
    """
    base_url = (settings.bluesky_client_url or "").rstrip("/")

    if error is not None:
        logger.warning("Facebook OAuth error: %s", error)
        error_params = urlencode({"oauth_error": error})
        return RedirectResponse(url=f"{base_url}/admin?{error_params}", status_code=303)

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    state_store = request.app.state.facebook_oauth_state
    pending = state_store.pop(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    import httpx as httpx_client

    from backend.crosspost.facebook import (
        FacebookOAuthTokenError,
        exchange_facebook_oauth_token,
    )

    try:
        result = await exchange_facebook_oauth_token(
            code=code,
            app_id=pending["app_id"],
            app_secret=pending["app_secret"],
            redirect_uri=pending["redirect_uri"],
        )
    except FacebookOAuthTokenError as exc:
        logger.error("Facebook OAuth callback error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook token exchange failed",
        ) from exc
    except httpx_client.HTTPError as exc:
        logger.error("Facebook OAuth HTTP error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook authentication failed",
        ) from exc

    raw_pages = result["pages"]
    if not isinstance(raw_pages, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected pages format from Facebook API",
        )
    pages: list[dict[str, str]] = raw_pages

    # Validate page dict structure (Issue #13)
    for pg in pages:
        if "access_token" not in pg or "id" not in pg:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Facebook Page data missing required fields (access_token, id)",
            )

    if len(pages) == 1:
        page = pages[0]
        credentials = {
            "page_access_token": page["access_token"],
            "page_id": page["id"],
            "page_name": page.get("name", ""),
        }
        account_name = page.get("name", f"Page {page['id']}")
        account_data = SocialAccountCreate(
            platform="facebook",
            account_name=account_name,
            credentials=credentials,
        )
        await _upsert_social_account(
            session,
            pending["user_id"],
            account_data,
            settings.secret_key,
            "facebook",
            account_name,
        )
        return RedirectResponse(url=f"{base_url}/admin", status_code=303)

    # Multiple pages: store in temp state for page selection
    page_selection_state = secrets.token_hex(32)
    state_store.set(
        page_selection_state,
        {
            "user_id": pending["user_id"],
            "pages": pages,
        },
    )

    page_params = urlencode({"fb_pages": page_selection_state})
    return RedirectResponse(url=f"{base_url}/admin?{page_params}", status_code=303)


@router.post(
    "/facebook/select-page",
    response_model=FacebookSelectPageResponse,
)
async def facebook_select_page(
    body: FacebookSelectPageRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> FacebookSelectPageResponse:
    """Finalize Facebook account by selecting a Page."""
    state_store = request.app.state.facebook_oauth_state
    pending = state_store.pop(body.state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired page selection state",
        )
    if pending["user_id"] != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User mismatch",
        )

    pages: list[dict[str, str]] = pending["pages"]
    page = next((p for p in pages if p["id"] == body.page_id), None)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page not found in OAuth results",
        )

    credentials = {
        "page_access_token": page["access_token"],
        "page_id": page["id"],
        "page_name": page.get("name", ""),
    }
    account_name = page.get("name", f"Page {page['id']}")
    account_data = SocialAccountCreate(
        platform="facebook",
        account_name=account_name,
        credentials=credentials,
    )
    await _upsert_social_account(
        session,
        user.id,
        account_data,
        settings.secret_key,
        "facebook",
        account_name,
    )
    return FacebookSelectPageResponse(account_name=account_name)


@router.get("/facebook/pages", response_model=FacebookPagesResponse)
async def facebook_pages(
    state: Annotated[str, Query()],
    user: Annotated[User, Depends(require_auth)],
    request: Request,
) -> FacebookPagesResponse:
    """Retrieve available Facebook Pages for selection.

    Uses the state token from the callback redirect to look up
    stored page data without consuming it.
    """
    from backend.schemas.crosspost import FacebookPageInfo

    state_store = request.app.state.facebook_oauth_state
    pending = state_store.get(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired page selection state",
        )
    if pending["user_id"] != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User mismatch",
        )

    pages: list[dict[str, str]] = pending["pages"]
    return FacebookPagesResponse(
        pages=[FacebookPageInfo(id=p["id"], name=p.get("name", "")) for p in pages]
    )
