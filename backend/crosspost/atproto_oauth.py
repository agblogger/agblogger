"""AT Protocol OAuth helpers: key generation, DPoP proofs, PKCE, client assertions."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import time
import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, cast

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1,
    EllipticCurvePrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

from backend.crosspost.http_utils import parse_json_object
from backend.crosspost.ssrf import ssrf_safe_client
from backend.exceptions import ExternalServiceError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

ATPROTO_TIMEOUT = 15.0


def _b64url(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_es256_keypair() -> tuple[EllipticCurvePrivateKey, dict[str, str]]:
    """Generate an ES256 (P-256) keypair and return (private_key, public_jwk)."""
    private_key = ec.generate_private_key(SECP256R1())
    public_numbers = private_key.public_key().public_numbers()
    x_bytes = public_numbers.x.to_bytes(32, "big")
    y_bytes = public_numbers.y.to_bytes(32, "big")
    kid = str(uuid.uuid4())
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(x_bytes),
        "y": _b64url(y_bytes),
        "kid": kid,
    }
    return private_key, jwk


def serialize_keypair(
    private_key: EllipticCurvePrivateKey, jwk: dict[str, str], path: Path
) -> None:
    """Serialize keypair to a JSON file (PEM private key + public JWK).

    Uses atomic write (temp file + rename) to avoid race conditions.
    """
    import os
    import tempfile

    pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    data = {"private_key_pem": pem.decode("ascii"), "jwk": jwk}
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".keypair_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, str(path))
    except BaseException:
        os.unlink(tmp_path)
        raise


def load_or_create_keypair(
    path: Path,
) -> tuple[EllipticCurvePrivateKey, dict[str, str]]:
    """Load keypair from file, or create and save a new one.

    Uses a lock file to avoid check-then-create races across concurrent callers.
    If the existing file is corrupted, it is replaced with a freshly generated keypair.
    """

    def _load_existing() -> tuple[EllipticCurvePrivateKey, dict[str, str]]:
        data = json.loads(path.read_text())
        private_key = load_pem_private_key(data["private_key_pem"].encode("ascii"), password=None)
        if not isinstance(private_key, EllipticCurvePrivateKey):
            raise TypeError("Stored key is not an elliptic curve private key")
        jwk = cast("dict[str, str]", data["jwk"])
        return private_key, jwk

    if path.exists():
        try:
            return _load_existing()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Corrupted keypair file %s, regenerating: %s", path, exc)
            path.unlink(missing_ok=True)
            # Fall through to create a new keypair

    lock_path = path.with_name(f".{path.name}.lock")

    # Remove stale lock files (older than 30 seconds) — H7
    if lock_path.exists():
        try:
            lock_age = time.time() - lock_path.stat().st_mtime
            if lock_age > 30:
                logger.warning(
                    "Removing stale keypair lock file (age: %.0fs): %s", lock_age, lock_path
                )
                lock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Stale keypair lock inspection failed for %s: %s", lock_path, exc)
            with contextlib.suppress(OSError):
                lock_path.unlink(missing_ok=True)

    lock_fd: int | None = None
    for _attempt in range(500):
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if path.exists():
                try:
                    return _load_existing()
                except (
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                    UnicodeDecodeError,
                ) as exc:
                    logger.warning("Corrupted keypair during lock wait: %s", exc)
                    # Fall through to retry — another process may fix it
            time.sleep(0.01)
    else:
        raise RuntimeError(f"Failed to acquire keypair lock for {path}")

    try:
        if path.exists():
            try:
                return _load_existing()
            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
            ) as exc:
                logger.warning("Corrupted keypair file after lock acquired, regenerating: %s", exc)
        private_key, jwk = generate_es256_keypair()
        serialize_keypair(private_key, jwk, path)
        return private_key, jwk
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(lock_path)


def create_dpop_proof(
    *,
    method: str,
    url: str,
    key: EllipticCurvePrivateKey,
    jwk: dict[str, str],
    nonce: str = "",
    access_token: str | None = None,
) -> str:
    """Create a DPoP proof JWT (ES256)."""
    headers = {"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk}
    payload: dict[str, str | int] = {
        "jti": str(uuid.uuid4()),
        "htm": method,
        "htu": url,
        "iat": int(time.time()),
    }
    if nonce:
        payload["nonce"] = nonce
    if access_token is not None:
        token_hash = hashlib.sha256(access_token.encode("ascii")).digest()
        payload["ath"] = _b64url(token_hash)
    return jwt.encode(payload, key, algorithm="ES256", headers=headers)


def create_pkce_challenge() -> tuple[str, str]:
    """Generate PKCE verifier and S256 challenge."""
    verifier_bytes = secrets.token_bytes(48)
    verifier = _b64url(verifier_bytes)
    challenge_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _b64url(challenge_hash)
    return verifier, challenge


def create_client_assertion(
    client_id: str,
    aud: str,
    key: EllipticCurvePrivateKey,
    kid: str,
) -> str:
    """Create a client assertion JWT for token endpoint authentication."""
    headers = {"alg": "ES256", "kid": kid}
    now = int(time.time())
    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": aud,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 60,
    }
    return jwt.encode(payload, key, algorithm="ES256", headers=headers)


class ATProtoOAuthError(ExternalServiceError):
    """Error during AT Protocol OAuth operations."""


async def _is_safe_url(url: str) -> bool:
    """Validate URL format: HTTPS scheme, non-localhost hostname, valid structure.

    DNS resolution and IP validation are handled at the transport level by
    SSRFSafeBackend; this function only checks URL format.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname in ("localhost", "127.0.0.1", "::1", "[::1]"):
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            return False
    except ValueError:
        pass  # Not an IP literal — DNS validation handled by SSRFSafeBackend
    return True


async def _resolve_handle_dns(handle: str) -> str | None:
    """Resolve an AT Protocol handle via DNS TXT lookup.

    Returns the DID string if found, or None as a simplified fallback.
    DNS resolution is not performed here for simplicity — returns None to
    fall through to the HTTP method.
    """
    return None


async def _resolve_handle_http(handle: str) -> str | None:
    """Resolve an AT Protocol handle via HTTP well-known endpoint."""
    url = f"https://{handle}/.well-known/atproto-did"
    if not await _is_safe_url(url):
        return None
    try:
        async with ssrf_safe_client(timeout=ATPROTO_TIMEOUT) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            did = resp.text.strip()
            if did.startswith("did:"):
                return did
    except httpx.HTTPError:
        logger.debug("HTTP handle resolution failed for %s", handle)
    return None


async def resolve_handle_to_did(handle: str) -> str:
    """Resolve an AT Protocol handle to a DID.

    Tries DNS TXT first, then HTTP well-known. Raises ATProtoOAuthError if both fail.
    """
    did = await _resolve_handle_dns(handle)
    if did:
        return did
    did = await _resolve_handle_http(handle)
    if did:
        return did
    msg = f"Could not resolve handle '{handle}' to a DID"
    raise ATProtoOAuthError(msg)


async def discover_auth_server(did: str) -> dict[str, Any]:
    """Discover the authorization server for a DID.

    Resolves DID document -> PDS URL -> OAuth protected resource ->
    authorization server metadata.

    Returns the authorization server metadata dict with 'pds_url' added.
    """
    # Step 1: Resolve DID document
    if did.startswith("did:plc:"):
        did_doc_url = f"https://plc.directory/{did}"
    elif did.startswith("did:web:"):
        domain = did.removeprefix("did:web:")
        did_doc_url = f"https://{domain}/.well-known/did.json"
    else:
        msg = f"Unsupported DID method: {did}"
        raise ATProtoOAuthError(msg)

    if not await _is_safe_url(did_doc_url):
        msg = f"Unsafe URL for DID resolution: {did_doc_url}"
        raise ATProtoOAuthError(msg)

    async with ssrf_safe_client(timeout=ATPROTO_TIMEOUT) as client:
        # Fetch DID document
        resp = await client.get(did_doc_url)
        if resp.status_code != 200:
            msg = f"Failed to fetch DID document for {did}: HTTP {resp.status_code}"
            raise ATProtoOAuthError(msg)
        did_doc = parse_json_object(
            resp, error_cls=ATProtoOAuthError, context="DID document endpoint"
        )

        # Step 2: Extract PDS URL from service array
        pds_url: str | None = None
        for service in did_doc.get("service", []):
            if service.get("id") == "#atproto_pds":
                pds_url = service.get("serviceEndpoint")
                break
        if not pds_url:
            msg = f"No PDS service found in DID document for {did}"
            raise ATProtoOAuthError(msg)

        # Step 3: Fetch OAuth protected resource metadata from PDS
        resource_url = f"{pds_url}/.well-known/oauth-protected-resource"
        if not await _is_safe_url(resource_url):
            msg = f"Unsafe PDS URL: {resource_url}"
            raise ATProtoOAuthError(msg)
        resp = await client.get(resource_url)
        if resp.status_code != 200:
            msg = f"Failed to fetch OAuth resource metadata from {pds_url}"
            raise ATProtoOAuthError(msg)
        resource_meta = parse_json_object(
            resp, error_cls=ATProtoOAuthError, context="OAuth resource metadata endpoint"
        )

        auth_servers = resource_meta.get("authorization_servers", [])
        if not auth_servers:
            msg = f"No authorization servers listed in resource metadata from {pds_url}"
            raise ATProtoOAuthError(msg)
        auth_server_url = auth_servers[0]

        # Step 4: Fetch authorization server metadata
        as_meta_url = f"{auth_server_url}/.well-known/oauth-authorization-server"
        if not await _is_safe_url(as_meta_url):
            msg = f"Unsafe auth server URL: {as_meta_url}"
            raise ATProtoOAuthError(msg)
        resp = await client.get(as_meta_url)
        if resp.status_code != 200:
            msg = f"Failed to fetch auth server metadata from {auth_server_url}"
            raise ATProtoOAuthError(msg)

        auth_meta = parse_json_object(
            resp,
            error_cls=ATProtoOAuthError,
            context="OAuth authorization server metadata endpoint",
        )
        auth_meta["pds_url"] = pds_url
        return auth_meta


async def _auth_server_post(
    url: str,
    data: dict[str, str],
    *,
    client_id: str,
    auth_server_issuer: str,
    private_key: EllipticCurvePrivateKey,
    jwk: dict[str, str],
    dpop_nonce: str = "",
) -> httpx.Response:
    """POST to an auth server with client assertion and DPoP proof.

    Handles automatic DPoP nonce rotation on 400 responses with use_dpop_nonce error.
    """
    if not await _is_safe_url(url):
        msg = f"Unsafe auth server URL: {url}"
        raise ATProtoOAuthError(msg)

    current_nonce = dpop_nonce

    async with ssrf_safe_client(timeout=ATPROTO_TIMEOUT) as client:
        for _attempt in range(2):
            assertion = create_client_assertion(
                client_id, auth_server_issuer, private_key, jwk["kid"]
            )
            dpop_proof = create_dpop_proof(
                method="POST", url=url, key=private_key, jwk=jwk, nonce=current_nonce
            )
            data_with_auth = {
                **data,
                "client_assertion": assertion,
                "client_assertion_type": ("urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
            }
            headers = {"DPoP": dpop_proof}
            resp = await client.post(url, data=data_with_auth, headers=headers)

            # Handle DPoP nonce rotation
            new_nonce = resp.headers.get("DPoP-Nonce", "")
            if resp.status_code == 400 and new_nonce:
                try:
                    body = resp.json()
                except ValueError:
                    return resp
                if isinstance(body, dict) and body.get("error") == "use_dpop_nonce":
                    current_nonce = new_nonce
                    continue
            return resp

    raise ATProtoOAuthError("Auth server DPoP nonce rotation exhausted")  # pragma: no cover


async def send_par_request(
    *,
    auth_server_meta: dict[str, Any],
    client_id: str,
    redirect_uri: str,
    did: str,
    scope: str,
    private_key: EllipticCurvePrivateKey,
    jwk: dict[str, str],
    dpop_nonce: str = "",
) -> dict[str, str]:
    """Send a Pushed Authorization Request (PAR).

    Returns dict with authorization_url, state, pkce_verifier, and dpop_nonce.
    """
    par_endpoint = auth_server_meta["pushed_authorization_request_endpoint"]
    auth_endpoint = auth_server_meta["authorization_endpoint"]
    issuer = auth_server_meta["issuer"]

    if not await _is_safe_url(auth_endpoint):
        msg = f"Unsafe authorization endpoint: {auth_endpoint}"
        raise ATProtoOAuthError(msg)

    verifier, challenge = create_pkce_challenge()
    state = secrets.token_urlsafe(32)

    data = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "login_hint": did,
    }

    resp = await _auth_server_post(
        par_endpoint,
        data,
        client_id=client_id,
        auth_server_issuer=issuer,
        private_key=private_key,
        jwk=jwk,
        dpop_nonce=dpop_nonce,
    )

    if resp.status_code not in (200, 201):
        msg = f"PAR request failed: HTTP {resp.status_code} — {resp.text}"
        raise ATProtoOAuthError(msg)

    par_resp = parse_json_object(resp, error_cls=ATProtoOAuthError, context="OAuth PAR endpoint")
    request_uri_value = par_resp.get("request_uri")
    if not isinstance(request_uri_value, str) or not request_uri_value:
        raise ATProtoOAuthError("OAuth PAR endpoint response missing request_uri")
    request_uri = request_uri_value
    new_nonce = resp.headers.get("DPoP-Nonce", dpop_nonce)

    auth_url_params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "request_uri": request_uri,
        }
    )
    authorization_url = f"{auth_endpoint}?{auth_url_params}"

    return {
        "authorization_url": authorization_url,
        "state": state,
        "pkce_verifier": verifier,
        "dpop_nonce": new_nonce,
    }


async def exchange_code_for_tokens(
    *,
    token_endpoint: str,
    auth_server_issuer: str,
    code: str,
    redirect_uri: str,
    pkce_verifier: str,
    client_id: str,
    private_key: EllipticCurvePrivateKey,
    jwk: dict[str, str],
    dpop_nonce: str = "",
) -> dict[str, Any]:
    """Exchange an authorization code for access and refresh tokens.

    Returns dict with access_token, refresh_token, sub, dpop_nonce, and other fields.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": pkce_verifier,
        "client_id": client_id,
    }

    resp = await _auth_server_post(
        token_endpoint,
        data,
        client_id=client_id,
        auth_server_issuer=auth_server_issuer,
        private_key=private_key,
        jwk=jwk,
        dpop_nonce=dpop_nonce,
    )

    if resp.status_code != 200:
        msg = f"Token exchange failed: HTTP {resp.status_code} — {resp.text}"
        raise ATProtoOAuthError(msg)

    token_data = parse_json_object(
        resp, error_cls=ATProtoOAuthError, context="OAuth token endpoint"
    )
    token_data["dpop_nonce"] = resp.headers.get("DPoP-Nonce", dpop_nonce)
    return token_data


async def refresh_access_token(
    *,
    token_endpoint: str,
    auth_server_issuer: str,
    refresh_token: str,
    client_id: str,
    private_key: EllipticCurvePrivateKey,
    jwk: dict[str, str],
    dpop_nonce: str = "",
) -> dict[str, Any]:
    """Refresh an access token using a refresh token.

    Returns dict with new access_token, refresh_token, dpop_nonce, and other fields.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    resp = await _auth_server_post(
        token_endpoint,
        data,
        client_id=client_id,
        auth_server_issuer=auth_server_issuer,
        private_key=private_key,
        jwk=jwk,
        dpop_nonce=dpop_nonce,
    )

    if resp.status_code != 200:
        msg = f"Token refresh failed: HTTP {resp.status_code} — {resp.text}"
        raise ATProtoOAuthError(msg)

    token_data = parse_json_object(
        resp, error_cls=ATProtoOAuthError, context="OAuth token refresh endpoint"
    )
    token_data["dpop_nonce"] = resp.headers.get("DPoP-Nonce", dpop_nonce)
    return token_data
