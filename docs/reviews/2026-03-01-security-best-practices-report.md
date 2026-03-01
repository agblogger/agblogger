# Security Best Practices Report

Date: 2026-03-01
Reviewer: Codex using the `security-best-practices` skill
Scope: Entire AgBlogger codebase

## Executive Summary

I reviewed the FastAPI backend, React frontend, auth/session handling, content rendering, filesystem access, sync, and cross-posting flows against the repository's own security guidance and the skill references for FastAPI and React.

I found 4 actionable issues:

- 1 High
- 1 Medium
- 2 Low

The highest-impact issue is an authorization bug: draft visibility is enforced by comparing a post's `author` string to `user.display_name`, but `display_name` is user-controlled and not unique. An invited or self-registered user can impersonate another author's display name and read that author's drafts.

## High Severity Findings

### SBP-001: Draft authorization is based on mutable, non-unique `display_name`

- Severity: High
- Rule ID: FASTAPI-AUTH-001
- Impact: A low-privilege user who registers with another author's display name can read that author's draft listings, draft post detail, draft assets, and draft cross-post targets.
- Location:
  - `backend/api/auth.py:242-250`
  - `backend/schemas/auth.py:21-28`
  - `backend/models/user.py:21-26`
  - `backend/services/auth_service.py:307-312`
  - `backend/api/posts.py:135`
  - `backend/api/posts.py:396-401`
  - `backend/api/content.py:87-99`
  - `backend/services/crosspost_service.py:119-123`
- Evidence:

```python
# backend/api/auth.py:242-250
user = User(
    username=body.username,
    email=body.email,
    password_hash=hash_password(body.password),
    display_name=body.display_name,
    is_admin=False,
    created_at=now,
    updated_at=now,
)
```

```python
# backend/models/user.py:21-26
username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
display_name: Mapped[str | None] = mapped_column(String, nullable=True)
```

```python
# backend/api/posts.py:135
draft_author = (user.display_name or user.username) if user else None
```

```python
# backend/api/posts.py:399-400
user_author = user.display_name or user.username
if post.author != user_author:
```

```python
# backend/api/content.py:94-95
user_author = user.display_name or user.username
if post.author != user_author:
```

```python
# backend/services/crosspost_service.py:120-121
actor_author = actor.display_name or actor.username
if not actor.is_admin and post_data.author != actor_author:
```

```python
# backend/services/auth_service.py:307-312
admin = User(
    username=settings.admin_username,
    ...
    display_name="Admin",
```

- Why this matters: the app is treating a presentation field as an authorization identity. Because `display_name` is optional, user-controlled, and not unique, it is not a safe ownership primitive.
- Fix:
  1. Stop authorizing draft access with `display_name` or any mutable string field.
  2. Persist a stable owner identifier on posts and draft assets, ideally `author_user_id`.
  3. During migration, fall back to username only for legacy posts when the stored owner ID is absent, and backfill IDs where possible.
  4. Add regression tests for registering `display_name="Admin"` and verifying that draft list/detail/content/cross-post access still returns `404`.
- Mitigation: Until ownership is migrated, reject duplicate `display_name` values and use `username` for draft authorization instead of `display_name`.
- False positive notes: This remains exploitable even when self-registration is disabled, because invite-based registration still lets a newly invited user choose any `display_name`.

## Medium Severity Findings

### SBP-002: Facebook OAuth and page-discovery requests place secrets and bearer tokens in URL query strings

- Severity: Medium
- Rule ID: FASTAPI-AUTH-002
- Impact: OAuth client secrets and access tokens can leak through HTTP access logs, reverse proxies, tracing systems, APM tools, or error telemetry that records full request URLs.
- Location:
  - `backend/crosspost/facebook.py:47-55`
  - `backend/crosspost/facebook.py:68-76`
  - `backend/crosspost/facebook.py:89-92`
- Evidence:

```python
# backend/crosspost/facebook.py:47-55
token_resp = await http_client.get(
    f"{FACEBOOK_GRAPH_API}/oauth/access_token",
    params={
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    },
```

```python
# backend/crosspost/facebook.py:68-76
ll_resp = await http_client.get(
    f"{FACEBOOK_GRAPH_API}/oauth/access_token",
    params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    },
```

```python
# backend/crosspost/facebook.py:89-92
pages_resp = await http_client.get(
    f"{FACEBOOK_GRAPH_API}/me/accounts",
    params={"access_token": long_lived_token},
```

- Why this matters: URL query strings are routinely logged outside application code. Even over HTTPS, secrets in URLs expand the number of places where compromise can occur.
- Fix:
  1. Prefer `Authorization: Bearer ...` headers for bearer tokens.
  2. If Facebook requires these parameters on specific endpoints, isolate these requests behind explicit log redaction and document the exception.
  3. Avoid placing `client_secret` in URL params when an equivalent form body or auth header is supported.
- Mitigation: Ensure proxy, load balancer, and observability layers redact query strings for `graph.facebook.com` requests.
- False positive notes: Some Graph API endpoints may require query parameters. If so, the issue is still the leakage surface, not transport security.

## Low Severity Findings

### SBP-003: The CSRF token is marked `HttpOnly`, but the backend mirrors it into response headers and the frontend persists it in `localStorage`

- Severity: Low
- Rule ID: REACT-CSRF-001
- Impact: Any same-origin script execution bug can immediately extract a reusable CSRF token, so the `HttpOnly` flag on the CSRF cookie provides no practical secrecy benefit.
- Location:
  - `backend/api/auth.py:80-89`
  - `backend/main.py:339-342`
  - `frontend/src/api/client.ts:14-30`
  - `frontend/src/api/client.ts:65-79`
- Evidence:

```python
# backend/api/auth.py:80-89
response.set_cookie(
    key="csrf_token",
    value=csrf_token,
    httponly=True,
    ...
)
response.headers["X-CSRF-Token"] = csrf_token
```

```python
# backend/main.py:339-342
csrf_token = request.cookies.get("csrf_token")
if csrf_token:
    response.headers.setdefault("X-CSRF-Token", csrf_token)
```

```typescript
// frontend/src/api/client.ts:19-30
return window.localStorage.getItem(CSRF_STORAGE_KEY)
...
window.localStorage.setItem(CSRF_STORAGE_KEY, token)
```

- Why this matters: CSRF defenses do not stop XSS, but the current design advertises `HttpOnly` protection while immediately re-exposing the same token to JavaScript and durable browser storage.
- Fix:
  1. Either keep the CSRF token script-readable and remove the misleading `HttpOnly` claim, or
  2. Move to a server-managed synchronizer-token/session design that does not require client-side persistence in `localStorage`.
  3. At minimum, avoid persisting the token across browser restarts.
- Mitigation: Keep CSP strict and continue treating XSS prevention as the primary defense.
- False positive notes: This is a defense-in-depth weakness, not a standalone CSRF bypass.

### SBP-004: One application secret is reused for both JWT signing and credential encryption

- Severity: Low
- Rule ID: FASTAPI-AUTH-003
- Impact: Compromise of `SECRET_KEY` simultaneously enables JWT forgery and decryption of stored social-account credentials, eliminating cryptographic compartmentalization.
- Location:
  - `backend/services/auth_service.py:44-49`
  - `backend/services/crypto_service.py:13-27`
- Evidence:

```python
# backend/services/auth_service.py:44-49
def create_access_token(data: dict[str, Any], secret_key: str, expires_minutes: int = 15) -> str:
    ...
    return str(jwt.encode(to_encode, secret_key, algorithm=ALGORITHM))
```

```python
# backend/services/crypto_service.py:13-21
def _derive_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_value(plaintext: str, secret_key: str) -> str:
    f = Fernet(_derive_key(secret_key))
```

- Why this matters: auth signing keys and data-encryption keys should be separated so that one secret compromise does not collapse multiple security boundaries at once.
- Fix:
  1. Introduce a dedicated credential-encryption key, or derive separate subkeys with HKDF using explicit context strings.
  2. Plan a credential re-encryption migration for stored social-account secrets.
- Mitigation: Rotate `SECRET_KEY` immediately if exposure is suspected, and reconnect encrypted social accounts after rotation.
- False positive notes: This is a key-management weakness, not proof of current secret exposure.

## Suggested Next Steps

1. Fix SBP-001 first. It is a real authorization bypass affecting draft confidentiality.
2. Then reduce secret leakage surface in the Facebook OAuth implementation.
3. After that, clean up the CSRF token exposure model and separate signing/encryption keys.
