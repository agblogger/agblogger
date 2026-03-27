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

- **Hardened browser cookies**: Authentication cookies must remain `HttpOnly`, `SameSite=Strict`, and `Secure` outside debug. Do not weaken these flags.
- **Cookie auth plus CSRF**: Unsafe browser requests under `/api/` must continue to require CSRF protection tied to the authenticated browser session. Do not add cookie-authenticated write endpoints that bypass this model.
- **Origin checks on login**: Browser login must continue to validate request origin metadata against configured allowed origins.
- **Rate limiting**: Authentication endpoints must remain rate-limited. Do not remove or materially relax login or refresh throttling.
- **Refresh token rotation**: Refresh must remain one-time-use from the client's perspective. A successful refresh should invalidate the prior refresh token before issuing a replacement.
- **No plaintext durable tokens**: Refresh tokens and similar long-lived secrets must be stored only as one-way hashes unless there is a documented cryptographic reason not to.
- **Side-channel resistance**: Keep timing-safe comparisons and anti-enumeration behavior for authentication failures.

### When adding new auth endpoints

1. Use `require_admin` or `get_current_admin` dependencies from `backend/api/deps.py`. Do not write ad-hoc auth checks inline.
2. If the endpoint accepts cookie auth and performs a state-changing operation, verify it is covered by the CSRF middleware (it is, as long as the path starts with `/api/` and the method is POST/PUT/PATCH/DELETE).
3. If the endpoint introduces a new token type, hash it before storage and validate expiration on use.
4. Add tests for: unauthenticated access (401), insufficient privileges (403), expired tokens, revoked tokens, and rate limiting.

### When modifying the login/refresh/logout flow

Touch all three layers together:
- **Backend**: token issuance, cookie handling, and CSRF token generation
- **Middleware**: CSRF enforcement and request-boundary checks
- **Frontend**: CSRF token fetch/caching and header injection

Test the full cycle: login sets cookies, authenticated requests include CSRF, refresh rotates tokens, logout clears everything.

## Authorization

### Endpoint protection

Every endpoint that modifies state or accesses user-specific data must declare its authorization requirement via dependency injection:

```python
# Read-only, public (may or may not be the admin)
user: Annotated[AdminUser | None, Depends(get_current_admin)]

# Requires admin authentication (every authenticated user is the admin)
user: Annotated[AdminUser, Depends(require_admin)]
```

Use the dependency chain for all authorization checks.

### Draft visibility

Draft posts and their co-located assets are visible only to their author. This is enforced in:
- Post listing: filters drafts by matching authenticated user's username against the post's `author` field
- Content file serving: returns 404 (not 403) for non-authors to avoid information disclosure
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

- **`InternalServerError`** (`backend/exceptions.py`) — for errors whose details must never reach clients: decryption failures, config validation, infrastructure port conflicts, and similar internal faults.
- **`ExternalServiceError`** (`backend/exceptions.py`) — for external service failures (OAuth, HTTP APIs) where details should be logged but not exposed to clients.
- **`ValueError`** — for business logic validation errors that are safe to forward to clients: invalid dates, bad input formats, and similar user-correctable problems.

Services must never import `HTTPException` from FastAPI. Raise `ValueError`, `InternalServerError`, or `ExternalServiceError` and let the API layer or global handlers translate to HTTP responses.

### Global exception handlers

The global exception handlers in `backend/main.py` catch unhandled errors at the framework boundary. Each logs the full traceback and returns a generic message. If you introduce a new exception type that could escape route handlers, add a corresponding global handler.

### External service interaction

All interactions with external services (pandoc, git, database, filesystem, network) must handle failures gracefully. Use bounded retries only when the operation is known to be safe to retry, log the real failure server-side, and return a generic client-facing error message.

## Input Validation and Sanitization

### HTML sanitization

All rendered HTML derived from markdown must continue to pass through the backend sanitizer before being served.

When modifying the sanitizer:
- Never add `script`, `object`, `embed`, `style`, `form`, or `button` to the allowed tags. `input` is allowed only for Pandoc task-list checkboxes, restricted to `type`, `checked`, and `disabled` attributes.
- `iframe` support, if kept, must stay restricted to explicitly approved embed providers and must remain aligned with CSP `frame-src`
- Never allow `on*` event handler attributes
- Never allow `javascript:` or `data:` URL schemes in `href`/`src`
- Test with XSS payloads: `<script>alert(1)</script>`, `<img onerror=alert(1) src=x>`, `<a href="javascript:alert(1)">`, `<div style="background:url(javascript:alert(1))">`

### Frontend HTML rendering

The frontend has a small number of components that render server-provided HTML with `dangerouslySetInnerHTML`. This is safe only because the backend sanitizes rendered HTML before serving it. Do not render user-supplied HTML on the frontend without backend sanitization.

### Uploaded asset delivery

Files reachable through `/api/content/*` must be treated as untrusted, even when they live under the managed content directory. Active document or script-capable types such as HTML, SVG, PDF, XML/XHTML, JSON, and JavaScript must not be served inline under the application origin. Preserve the current pattern of forcing these responses to download and attaching a restrictive per-response CSP.

### Path traversal protection

The content file endpoint uses multiple layers of defense. When modifying file-serving or path logic:
1. Maintain the `..` component rejection
2. Maintain the allowed prefix check (`posts/`, `assets/`)
3. Use `.resolve()` to follow symlinks before checking containment
4. Verify the resolved path stays within `content_dir` via `is_relative_to()`

Add regression tests for traversal attempts: `../etc/passwd`, `posts/../../etc/passwd`, symlink escapes.

### Sync path boundaries

Sync endpoints must stay narrower than the raw content root. Preserve the managed sync surface: site config, labels, top-level markdown pages, and non-hidden files under managed post and asset trees. Hidden files and private application state must remain unreachable through sync APIs.

### Pydantic validation

All API request bodies use Pydantic schemas. When adding new endpoints:
- Define a schema in `backend/schemas/` with explicit field types and constraints (`Field(ge=1, le=100)`, etc.)
- Do not accept raw `dict` or `Any`-typed request bodies

## Cryptography

### Credential encryption

Cross-post OAuth credentials are encrypted at rest, keyed to the application secret. When working with cross-post accounts:
- Always use `encrypt_value()` before database writes and `decrypt_value()` after reads
- Never store raw JSON credentials in the database
- If decryption or post-decryption parsing fails, fail closed and require the user to reconnect the account; do not fall back to plaintext JSON stored in the database
- Never log decrypted credential values

### Upload size enforcement

Multipart upload routes are protected by request-size limits at both the proxy and application layers. Keep the edge limits in `Caddyfile` / `Caddyfile.production` aligned with the app middleware in `backend/main.py` and the shared thresholds in `backend/services/upload_limits.py`. Reject oversized multipart requests before form parsing whenever possible.

### Token generation

Use `secrets.token_urlsafe()` for all token generation. Do not use `random`, `uuid4`, or other non-cryptographic sources.

## Outbound Integrations

Outbound requests to social platforms and OAuth providers are a separate trust boundary. Treat all provider-controlled URLs, metadata documents, and token responses as untrusted input.

### Outbound HTTP safety

- Preserve SSRF protections for outbound HTTP clients. Do not replace the hardened outbound client path with a generic client for provider discovery, OAuth flows, or publication requests.
- Resolve and validate remote destinations at connection time, not just by pre-validating URLs as strings.
- Do not allow integrations to reach loopback, private, link-local, multicast, reserved, or Unix-socket destinations.

### OAuth and provider flows

- Preserve PKCE, state validation, issuer validation, and equivalent anti-forgery checks for OAuth-style flows.
- Bind callbacks and token exchanges to the pending authorization state created by the same user flow. Do not accept partially validated callback parameters.
- Fail closed on malformed or incomplete token responses. Do not infer missing security-relevant fields.
- Never trust provider metadata or discovery responses without the same outbound-request hardening used for other third-party HTTP calls.

## Content Security Policy (CSP)

- **All fonts, scripts, and stylesheets must be self-hosted.** Do not add CDN `@import` or `<link>` tags pointing to third-party domains (e.g., Google Fonts, cdnjs, unpkg). These will be silently blocked in production.
- **Images** are the main exception: external HTTPS images are allowed, but scripts and styles are not.
- **Inline styles** are currently allowed for existing frontend rendering needs. Do not broaden script execution allowances to match that exception.
- If a new third-party resource is genuinely needed, self-host it (e.g., fontsource for fonts, npm packages for libraries) rather than relaxing the CSP.
- `frame-ancestors 'none'` prevents clickjacking. Do not relax this unless embedding is an explicit requirement.
- Keep any allowed embed domains aligned between the sanitizer and CSP.

## Browser Security Headers

- Preserve `X-Content-Type-Options: nosniff` so browsers do not reinterpret responses as a more dangerous content type.
- Preserve `X-Frame-Options: DENY` and `frame-ancestors 'none'` unless embedding the app becomes an explicit, reviewed requirement.
- Preserve `Referrer-Policy` unless a concrete integration requires a different policy and the privacy tradeoff has been reviewed.
- Preserve `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` unless you have a concrete cross-origin integration that requires something weaker.
- `Permissions-Policy` is deny-by-default for unused browser features. If a frontend change needs a browser capability such as camera, microphone, geolocation, clipboard, fullscreen, or Web Share, update the header in `backend/config.py` and add a regression test proving the intended capability still works.

## Trust Boundary Controls

### Middleware

- **TrustedHostMiddleware**: Required in production. Rejects requests with unexpected `Host` headers. Do not introduce wildcard-style permissive defaults.
- **CORS**: Empty origins by default (no cross-origin access). Dev mode adds `localhost:5173` and `localhost:8000`. Do not add wildcard `*` origins in production.
- **Trusted proxy IPs**: `X-Forwarded-For` is only trusted when the direct peer IP is in `TRUSTED_PROXY_IPS`. Do not trust forwarded headers unconditionally.

### Production fail-fast guards

Startup validation enforces basic production security requirements for secrets, admin bootstrap credentials, trusted host configuration, and externally visible OAuth client URLs. Do not bypass these checks outside explicit debug/test scenarios. Do not weaken the minimum requirements without a clear security review.

## Logging

- Log security events (failed auth, rate limiting, origin rejection, path traversal attempts) at WARNING or ERROR level.
- Never log plaintext passwords, tokens, or decrypted credentials.
- Use `exc_info=True` (or pass the exception directly) for error-level logs so the traceback is captured.

## Infrastructure

### Docker

- The application runs as the non-root `agblogger` user. Do not add `USER root` or `--privileged` flags.
- Do not copy dev dependencies or build tools into the production image.
- AgBlogger is internal-only in `docker-compose.yml` (`expose: 8000`, not `ports`). Only Caddy publishes ports to the host.

### GoatCounter API Token

- The GoatCounter API token must never be exposed publicly.
- Do not add endpoints, logging, or error messages that expose the token value to clients.
- Do not route GoatCounter traffic over public networks. All communication with GoatCounter must stay on the internal Docker network.

### Subprocess safety

- Prefer argument lists over shell command strings. Do not use shell invocation for operations that can be expressed as fixed argv.
- Keep executable names fixed and validate any user-influenced refs, paths, or identifiers before passing them to subprocesses.
- Set timeouts for subprocess calls and handle failure paths without crashing the server.
- Do not return raw subprocess stderr/stdout to clients when it may expose internal paths, commands, or environment details.
