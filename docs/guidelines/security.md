# Security Guidelines

Development guidelines for maintaining and extending AgBlogger's security posture. Read `docs/arch/security.md` for the architectural description of what exists; this document covers how to work with it safely.

## General Principles

- Every exception must be handled gracefully. Never silently swallow exceptions — log them, surface an appropriate error, or propagate them.
- Never expose *internal* server error details to clients. Route handlers and global exception handlers must return generic messages for *internal* server errors. Log the full exception server-side.
- Business logic errors (input validation, invalid action, etc.) are NOT internal server errors: clients should be informed what went wrong when the error is a direct result of invalid user action or input.
- Every security-sensitive change must include failing-first regression tests covering abuse paths, not only happy paths.
- Read `docs/arch/security.md` before modifying any code related to authentication, authorization, input validation, error handling, or infrastructure security.

## Authentication

Authentication is a coupled system spanning backend token logic, cookie handling, the CSRF endpoint/middleware, and frontend CSRF token caching. Do not change one side in isolation.

### What to preserve

- **Cookie flags**: `access_token` and `refresh_token` must remain `HttpOnly`, `SameSite=Strict`, and `Secure` outside debug. These are set in `backend/api/auth.py:_set_auth_cookies()`. Do not weaken any of these flags.
- **Stateless CSRF**: Unsafe `/api/*` methods with cookie auth require `X-CSRF-Token` matching the HMAC-derived token for the current access cookie. The middleware lives in `backend/main.py`, the token helpers live in `backend/services/csrf_service.py`, and the frontend fetches/caches the token via `frontend/src/api/`.
- **Login origin enforcement**: Validates `Origin`/`Referer` against allowed origins. Configured via `auth_enforce_login_origin` in `backend/config.py`.
- **Rate limiting**: Sliding-window counters on login (`login:{ip}:{username}`) and refresh (`refresh:{ip}`) endpoints. Do not remove or relax the limits.
- **Refresh token rotation**: On refresh, the old token is deleted before issuing a new pair. This prevents reuse of stolen tokens after legitimate rotation.
- **Hashed token storage**: Refresh tokens, PATs, and invite codes are SHA-256 hashed before database storage (`auth_service.hash_token()`). Never store plaintext token values.
- **Timing-safe comparison**: Username enumeration is mitigated with a dummy bcrypt check on failed lookups. CSRF token comparison uses `secrets.compare_digest()`.

### When adding new auth endpoints

1. Use `require_auth` or `require_admin` dependencies from `backend/api/deps.py`. Do not write ad-hoc auth checks inline.
2. If the endpoint accepts cookie auth and performs a state-changing operation, verify it is covered by the CSRF middleware (it is, as long as the path starts with `/api/` and the method is POST/PUT/PATCH/DELETE).
3. If the endpoint introduces a new token type, hash it before storage and validate expiration on use.
4. Add tests for: unauthenticated access (401), insufficient privileges (403), expired tokens, revoked tokens, and rate limiting.

### When modifying the login/refresh/logout flow

Touch all three layers together:
- **Backend**: token creation, cookie setting, CSRF token generation (`backend/api/auth.py`)
- **Middleware**: CSRF validation logic (`backend/main.py`)
- **Frontend**: CSRF token fetch/caching and header injection (`frontend/src/api/`)

Test the full cycle: login sets cookies, authenticated requests include CSRF, refresh rotates tokens, logout clears everything.

## Authorization

### Endpoint protection

Every endpoint that modifies state or accesses user-specific data must declare its authorization requirement via dependency injection:

```python
# Read-only, public
user: Annotated[User | None, Depends(get_current_user)]

# Requires any authenticated user
user: Annotated[User, Depends(require_auth)]

# Requires admin role
user: Annotated[User, Depends(require_admin)]
```

Do not inline auth checks like `if not user.is_admin: raise ...` inside handlers. Use the dependency chain.

### Draft visibility

Draft posts and their co-located assets are visible only to their author. This is enforced in:
- Post listing: filters drafts by matching authenticated user's username against the post's `author` field
- Content file serving: `backend/api/content.py:_check_draft_access()` returns 404 (not 403) for non-authors to avoid information disclosure
- Direct post access: same author-matching logic

When adding new endpoints that serve post content or metadata, check whether draft posts should be filtered.

## Error Handling

### Route handlers

Catch expected failures (database errors, file I/O, external service calls) and return appropriate HTTP status codes with generic messages:

```python
# Good
except OSError:
    logger.error("Failed to read file %s", path, exc_info=True)
    raise HTTPException(status_code=500, detail="Storage operation failed")

# Bad — leaks internal path
except OSError as exc:
    raise HTTPException(status_code=500, detail=str(exc))
```

### Exception type conventions

Use the correct exception type to control what clients see:

- **`InternalServerError`** (`backend/exceptions.py`) — for errors whose details must never reach clients: decryption failures, config validation, infrastructure port conflicts, etc. The global handler returns a generic `"Internal server error"` (500) and logs the full details server-side.
- **`ExternalServiceError`** (`backend/exceptions.py`) — for external service failures (OAuth, HTTP APIs) where details should be logged but not exposed to clients. The global handler returns `"External service error"` (502).
- **`ValueError`** — for business logic validation errors that are safe to forward to clients: invalid dates, bad input formats, etc. The global handler returns `str(exc)` as the 422 detail.

Services must never import `HTTPException` from FastAPI. Raise `ValueError`, `InternalServerError`, or `ExternalServiceError` and let the API layer or global handlers translate to HTTP responses.

### Global exception handlers

The global exception handlers in `backend/main.py` catch unhandled errors at the framework boundary. Each logs the full traceback and returns a generic message. If you introduce a new exception type that could escape route handlers, add a corresponding global handler.

### External service interaction

All interactions with external services (pandoc, git, database, filesystem, network) must handle failures gracefully. The pandoc renderer demonstrates the pattern: catch `httpx.NetworkError`, attempt a restart, retry once, then raise `RenderError` with a generic message.

## Input Validation and Sanitization

### HTML sanitization

All Pandoc-rendered HTML passes through the allowlist-based sanitizer (`backend/pandoc/renderer.py:_HtmlSanitizer`) before being served. The sanitizer:

- Strips all tags not in `_ALLOWED_TAGS`
- Allows only `class` and `id` as global attributes, with tag-specific extras (e.g., `href` on `<a>`, `src` on `<img>`)
- Validates URLs via `_is_safe_url()`: blocks `javascript:`, `data:` (in href/src), and protocol-relative (`//`) URLs
- Escapes all text content and attribute values

When modifying the sanitizer:
- Never add `script`, `object`, `embed`, `style`, `form`, `input`, or `button` to the allowed tags
- `iframe` is conditionally allowed only for YouTube embed/shorts URLs (`_YOUTUBE_SRC_RE`). The sanitizer forces sandbox, referrerpolicy, and loading attributes. Never extend iframe support to other domains without updating CSP `frame-src`.
- Never allow `on*` event handler attributes
- Never allow `javascript:` or `data:` URL schemes in `href`/`src`
- Test with XSS payloads: `<script>alert(1)</script>`, `<img onerror=alert(1) src=x>`, `<a href="javascript:alert(1)">`, `<div style="background:url(javascript:alert(1))">`

### Frontend HTML rendering

The frontend uses `dangerouslySetInnerHTML` in several components (`PostPage`, `EditorPage`, `SearchPage`, `PageViewPage`, `AdminPage`) to render server-provided HTML. This is safe because the backend sanitizes all rendered HTML before serving it. Do not render user-supplied HTML on the frontend without backend sanitization.

### Uploaded asset delivery

Files reachable through `/api/content/*` must be treated as untrusted, even when they live under the managed content directory. Active document or script-capable types such as HTML, SVG, PDF, XML/XHTML, JSON, and JavaScript must not be served inline under the application origin. Preserve the current pattern in `backend/api/content.py`: force these responses to download with `Content-Disposition: attachment` and attach a restrictive per-response CSP.

### Path traversal protection

The content file endpoint (`backend/api/content.py:_validate_path()`) uses four layers of defense. When modifying file-serving or path logic:
1. Maintain the `..` component rejection
2. Maintain the allowed prefix check (`posts/`, `assets/`)
3. Use `.resolve()` to follow symlinks before checking containment
4. Verify the resolved path stays within `content_dir` via `is_relative_to()`

Add regression tests for traversal attempts: `../etc/passwd`, `posts/../../etc/passwd`, symlink escapes.

### Sync path boundaries

Sync endpoints must stay narrower than the raw content root. Preserve the managed sync surface in `backend/services/sync_service.py` and `backend/api/sync.py`: `index.toml`, `labels.toml`, top-level `.md` pages, and all non-hidden files recursively under `posts/` and `assets/`. Hidden files and private application state must remain unreachable through sync APIs.

### Pydantic validation

All API request bodies use Pydantic schemas. When adding new endpoints:
- Define a schema in `backend/schemas/` with explicit field types and constraints (`Field(ge=1, le=100)`, etc.)
- Do not accept raw `dict` or `Any`-typed request bodies

## Cryptography

### Credential encryption

Cross-post OAuth credentials are encrypted at rest via Fernet (`backend/services/crypto_service.py`), keyed to the application `SECRET_KEY`. When working with cross-post accounts:
- Always use `encrypt_value()` before database writes and `decrypt_value()` after reads
- Never store raw JSON credentials in the database
- If decryption or post-decryption parsing fails, fail closed and require the user to reconnect the account; do not fall back to plaintext JSON stored in the database
- Never log decrypted credential values

### Upload size enforcement

Multipart upload routes are protected by request-size limits at both the proxy and application layers. Keep the edge limits in `Caddyfile` / `Caddyfile.production` aligned with the app middleware in `backend/main.py` and the shared thresholds in `backend/services/upload_limits.py`. Reject oversized multipart requests before form parsing whenever possible.

### Token generation

Use `secrets.token_urlsafe()` for all token generation. Do not use `random`, `uuid4`, or other non-cryptographic sources. Follow the existing prefix conventions: `agpat_` for PATs, `aginvite_` for invite codes.

## Content Security Policy (CSP)

The backend enforces a strict CSP via `backend/config.py:content_security_policy`:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' https: data:; font-src 'self' data:; connect-src 'self';
frame-src https://www.youtube.com https://www.youtube-nocookie.com;
base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

### Rules

- **All fonts, scripts, and stylesheets must be self-hosted.** Do not add CDN `@import` or `<link>` tags pointing to third-party domains (e.g., Google Fonts, cdnjs, unpkg). These will be silently blocked in production.
- **Images** are the exception: `img-src 'self' https: data:` allows external HTTPS images.
- **Inline styles** are allowed (`'unsafe-inline'`) for Tailwind and KaTeX.
- If a new third-party resource is genuinely needed, self-host it (e.g., fontsource for fonts, npm packages for libraries) rather than relaxing the CSP.
- Do not add `'unsafe-eval'` to `script-src`. The custom Semgrep rule (`.semgrep.yml`) blocks `eval()` and `new Function()`.
- `frame-ancestors 'none'` prevents clickjacking. Do not relax this unless embedding is an explicit requirement.

## Browser Security Headers

- Preserve `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` unless you have a concrete cross-origin integration that requires something weaker.
- `Permissions-Policy` is deny-by-default for unused browser features. If a frontend change needs a browser capability such as camera, microphone, geolocation, clipboard, fullscreen, or Web Share, update the header in `backend/config.py` and add a regression test proving the intended capability still works.

## Trust Boundary Controls

### Middleware

- **TrustedHostMiddleware**: Required in production. Rejects requests with unexpected `Host` headers. Do not introduce wildcard-style permissive defaults.
- **CORS**: Empty origins by default (no cross-origin access). Dev mode adds `localhost:5173` and `localhost:8000`. Do not add wildcard `*` origins in production.
- **Trusted proxy IPs**: `X-Forwarded-For` is only trusted when the direct peer IP is in `TRUSTED_PROXY_IPS`. Do not trust forwarded headers unconditionally.

### Production fail-fast guards

`Settings.validate_runtime_security()` in `backend/config.py` enforces:
- `SECRET_KEY` not default and >= 32 characters
- `ADMIN_PASSWORD` not default and >= 8 characters
- `TRUSTED_HOSTS` non-empty and not a catch-all wildcard
- `BLUESKY_CLIENT_URL`, when set, is a canonical `https://` origin

Do not bypass these outside explicit debug/test scenarios. Do not weaken the thresholds.

`docker-compose.yml` requires `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `TRUSTED_HOSTS` via `${VAR?message}` syntax. Do not make these optional.

## Logging

- Log security events (failed auth, rate limiting, origin rejection, path traversal attempts) at WARNING or ERROR level.
- Never log plaintext passwords, tokens, invite codes, or decrypted credentials.
- Use `exc_info=True` (or pass the exception directly) for error-level logs so the traceback is captured.

## Dependency Security

When adding dependencies:
- Run `just check-static` to verify no new vulnerabilities are introduced.
- For Python: `uv add <package>` then `uv run pip-audit`.
- For npm: `cd frontend && npm install <package>` then `npm audit`.
- Font packages using OFL-1.1 are already allowlisted in `trivy.yaml`. Other non-standard licenses may need explicit acknowledgment.

## Infrastructure

### Docker

- The application runs as the non-root `agblogger` user. Do not add `USER root` or `--privileged` flags.
- The multi-stage build discards the frontend build stage. Do not copy dev dependencies or build tools into the production image.
- AgBlogger is internal-only in `docker-compose.yml` (`expose: 8000`, not `ports`). Only Caddy publishes ports to the host.

### API documentation

OpenAPI docs (`/docs`, `/redoc`, `/openapi.json`) are disabled by default in production (`expose_docs=False`). Do not enable them in production unless explicitly required.

## Testing Security Changes

Every security-related change must include tests. Use this checklist:

### Authentication tests
- Unauthenticated request returns 401
- Invalid credentials return 401
- Expired token returns 401
- Revoked token returns 401
- Rate-limited request returns 429 with `Retry-After` header
- Cross-origin login returns 403

### Authorization tests
- Non-admin accessing admin endpoint returns 403
- Non-author accessing draft content returns 404

### Input validation tests
- Path traversal (`..`) returns 400
- Forbidden prefix returns 403
- XSS payload in markdown is sanitized in rendered output
- Invalid URL schemes (`javascript:`, `data:`) are stripped from href/src

### Error handling tests
- External service failure returns generic error message, not internal details
- Exception traceback is not present in response body
