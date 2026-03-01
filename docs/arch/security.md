# Security

## Overview

AgBlogger implements defense-in-depth across authentication, authorization, transport, content handling, and infrastructure. Security controls are layered so that no single failure compromises the system.

## Authentication

### Passwords

Passwords are hashed with bcrypt and auto-generated salts (`backend/services/auth_service.py`). Authentication performs a dummy bcrypt check on failed username lookups to prevent timing-based username enumeration.

### JWT Access Tokens

Short-lived (15 min default) HS256 JWTs carry `sub` (user ID), `username`, `is_admin`, and `type: "access"`. They are signed with a context-separated key derived from `SECRET_KEY` via HMAC-SHA256 (`backend/services/key_derivation.py`), not the raw application secret. Created in `auth_service.create_access_token()`, validated in `backend/api/deps.py:get_current_user()` with explicit type check.

### Refresh Token Rotation

Refresh tokens are 48-byte `secrets.token_urlsafe` values. Only their SHA-256 hash is stored in the database. On refresh, the old token is deleted and a new pair is issued — a stolen refresh token cannot be reused after legitimate rotation (`auth_service.refresh_tokens()`).

### Personal Access Tokens (PATs)

Long-lived tokens for CLI/API access with format `agpat_{secrets.token_urlsafe(48)}`. Hashed with SHA-256 before storage, support optional expiration, and track `last_used_at`. Revocable per-token (`auth_service.revoke_personal_access_token()`). Accepted only via Bearer header, never via cookies.

### Invite Codes

Single-use registration tokens with format `aginvite_{secrets.token_urlsafe(24)}`. Hashed before storage, configurable expiration (default 7 days, max 90). Used-at timestamp and consuming user tracked for audit.

### Cookie Security

Auth cookies are set with:

- `access_token`, `refresh_token`: `HttpOnly=True` — prevents JavaScript access
- `SameSite=Strict` — prevents cross-site request attachment
- `Secure=True` in production (keyed to `debug=False`)
- Scoped `max_age` matching token lifetimes

Set in `backend/api/auth.py:_set_auth_cookies()`, cleared on logout via `_clear_auth_cookies()`.

### CSRF Protection

Stateless CSRF protection is implemented as HTTP middleware (`backend/main.py`). For unsafe methods (POST/PUT/PATCH/DELETE) on `/api/*` paths with cookie-based auth, the `X-CSRF-Token` request header must match the expected HMAC-derived token for the current `access_token` cookie. The frontend fetches the token from `GET /api/auth/csrf`, caches it in memory, and refreshes that cache from login/refresh responses. Comparison uses `secrets.compare_digest()` for timing-safe equality. Login and Bearer-authenticated requests are exempt.

### Login Origin Enforcement

Login requests with an `Origin` or `Referer` header are validated against the app's own URL and configured CORS origins (`backend/api/auth.py:_enforce_login_origin()`). Requests from unknown origins receive 403. Configurable via `auth_enforce_login_origin` (default True).

### Rate Limiting

In-memory sliding-window rate limiter (`backend/services/rate_limit_service.py`) applied to:

- **Login**: keyed by `login:{client_ip}:{username}`, default 5 failures per 300s window
- **Refresh**: keyed by `refresh:{client_ip}`, default 10 failures per 300s window

Returns 429 with `Retry-After` header when exceeded. Counters reset on successful authentication.

### Trusted Proxy Handling

`X-Forwarded-For` is only trusted when the direct peer IP is in the `TRUSTED_PROXY_IPS` list (`backend/api/auth.py:_get_client_ip()`). Otherwise the socket peer IP is used for rate-limit keys, preventing IP spoofing.

### Admin Bootstrap

On startup, `ensure_admin_user()` creates the initial admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD` environment variables. The default password `"admin"` is an insecure sentinel that fails production validation.

## Authorization

### Dependency Injection

Protected endpoints use FastAPI dependency injection (`backend/api/deps.py`):

- `get_current_user()` — returns authenticated user or `None`
- `require_auth()` — raises 401 if unauthenticated
- `require_admin()` — raises 403 if not admin

### Role Model

| Role | Access |
|------|--------|
| Unauthenticated | Read published posts, labels, pages, search |
| Authenticated | Above + cross-post, user-scoped actions |
| Admin | Above + post CRUD, sync, admin panel |

### Draft Visibility

Draft posts and their co-located assets are visible only to their author. Ownership is enforced with the stable `author_username` field in post front matter and `PostCache`, with limited legacy fallback only while rebuilding older content that lacks the field. The content endpoint (`backend/api/content.py:_check_draft_access()`) queries the post cache to verify draft status and owner match. Non-authors receive 404 (not 403) to avoid information disclosure.

## Content Security Policy (CSP)

Strict allowlist-based CSP configured in `backend/config.py`:

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' https: data:;
font-src 'self' data:;
connect-src 'self';
frame-src https://www.youtube.com https://www.youtube-nocookie.com;
base-uri 'self';
form-action 'self';
frame-ancestors 'none'
```

Applied via the `security_headers` middleware in `backend/main.py`. All fonts, scripts, and stylesheets must be self-hosted. External images are allowed over HTTPS. Inline styles are permitted for Tailwind and KaTeX. `frame-src` allows only YouTube embeds. `frame-ancestors 'none'` prevents framing (clickjacking).

## HTTP Security Headers

Applied by the `security_headers` middleware (`backend/main.py`) when `security_headers_enabled=True` (default):

- `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing
- `X-Frame-Options: DENY` — clickjacking protection (belt-and-suspenders with CSP `frame-ancestors`)
- `Referrer-Policy: strict-origin-when-cross-origin` — limits referrer leakage
- `Content-Security-Policy` — as described above

## Middleware Stack

Applied in `backend/main.py:create_app()`:

1. **GZipMiddleware** — response compression (min 500 bytes)
2. **CORSMiddleware** — empty origins by default (no cross-origin access); `allow_credentials=True` for cookie auth
3. **TrustedHostMiddleware** — rejects requests with invalid Host headers; required in production via `trusted_hosts` setting
4. **CSRF middleware** — double-submit cookie validation
5. **Security headers middleware** — CSP and hardening headers

## Input Validation and Sanitization

### HTML Sanitization

Pandoc-rendered HTML passes through an allowlist-based sanitizer (`backend/pandoc/renderer.py:_HtmlSanitizer`). The sanitizer:

- Allows a fixed set of semantic tags (headings, paragraphs, lists, tables, code blocks, links, images)
- Strips all tags not in the allowlist (script, object, embed, style, form, etc.)
- Conditionally allows `<iframe>` only when `src` matches YouTube embed/shorts URLs; forces `sandbox="allow-scripts allow-same-origin allow-popups"`, `allowfullscreen`, `referrerpolicy="no-referrer"`, and `loading="lazy"` on all allowed iframes; rejected iframes are replaced with a user-visible notification
- Allows only `class` and `id` as global attributes, plus tag-specific attributes (`href`/`title` on `<a>`, `alt`/`src`/`title` on `<img>`, `colspan`/`rowspan` on `<td>`/`<th>`)
- Validates URLs: allows relative paths, `http`, `https`, `mailto`, `tel` schemes; blocks `javascript:`, `data:`, and protocol-relative URLs
- Validates `id` values against `^[a-zA-Z][a-zA-Z0-9:_-]*$`
- Escapes all text content and attribute values via `html.escape()`

Excerpts use a stricter pipeline (`render_markdown_excerpt()`):

- Pandoc input format disables raw HTML (`markdown-raw_html+...`)
- Excerpt sanitization removes media-bearing tags such as `<img>` and task-list `<input>`
- This prevents timeline/search excerpt cards from triggering remote media fetches while still preserving inline markdown formatting rendered by Pandoc

### Path Traversal Protection

The content file endpoint (`backend/api/content.py:_validate_path()`) enforces four layers:

1. Rejects `..` in path components
2. Whitelists allowed prefixes (`posts/`, `assets/`)
3. Resolves via `.resolve()` to follow symlinks
4. Verifies the resolved path stays within `content_dir` via `is_relative_to()`

### URL Rewriting

Relative URLs in rendered HTML are rewritten to absolute `/api/content/` paths (`renderer.py:rewrite_relative_urls()`). Paths that escape the content root after normalization are left unchanged.

### Pydantic Schema Validation

All API request bodies are validated against Pydantic schemas (`backend/schemas/`), enforcing types, ranges, and required fields before handler code executes.

## Cryptography

### Credential Encryption at Rest

Cross-post OAuth credentials are encrypted with Fernet symmetric encryption (`backend/services/crypto_service.py`). The encryption key is derived from `SECRET_KEY` with a dedicated HMAC-SHA256 context that is distinct from JWT signing. Plaintext credentials are never stored in the database.

### Token Hashing

Refresh tokens, PATs, and invite codes are hashed with SHA-256 before database storage (`auth_service.hash_token()`). A database dump does not reveal active token values.

## Error Handling

### Global Exception Handlers

Exception handlers in `backend/main.py` catch unhandled errors at the framework boundary:

| Exception | HTTP Status | Client Message |
|-----------|-------------|----------------|
| `InternalServerError` | 500 | "Internal server error" |
| `RenderError` | 502 | "Rendering service unavailable" |
| `RuntimeError` | 500 | "Internal processing error" |
| `OSError` | 500 | "Storage operation failed" |
| `YAMLError` | 422 | "Invalid content format" |
| `JSONDecodeError` | 500 | "Data integrity error" |
| `ValueError` | 422 | `str(exc)` (business logic errors safe for clients) |
| `TypeError` | 500 | "Internal server error" |
| `CalledProcessError` | 502 | "External process failed" |
| `UnicodeDecodeError` | 422 | "Invalid content encoding" |
| `OperationalError` | 503 | "Database temporarily unavailable" |
| `RequestValidationError` | 422 | Structured field-level errors |

All handlers log the full exception with traceback server-side while returning only generic messages to clients. `InternalServerError` is used for errors whose details must never reach clients (decryption failures, config validation, infrastructure issues). `ValueError` is the only handler that forwards `str(exc)` to clients, reserved for business logic validation errors.

### Exception Type Conventions

- **`InternalServerError`** (`backend/exceptions.py`): Raise for internal errors (decryption, config, infrastructure) whose messages contain sensitive details.
- **`ValueError`**: Raise for business logic validation (invalid dates, bad formats) where the message is safe for client display.
- **Service layer rule**: Services must not import `HTTPException`. Raise `ValueError` or `InternalServerError`; the API layer translates to HTTP responses.

### Pandoc Resilience

The renderer catches `httpx.NetworkError` (covers `ConnectError`, `ReadError`, `WriteError`) and attempts a server restart before retrying. `ReadTimeout` is caught separately. All failures surface as `RenderError`, which the cache service handles gracefully by skipping the affected post with a warning.

## Production Fail-Fast Guards

`Settings.validate_runtime_security()` (`backend/config.py`) runs on startup (called from `backend/main.py:lifespan()`). In non-debug mode, it enforces:

- `SECRET_KEY` must not be the dev sentinel and must be >= 32 characters
- `ADMIN_PASSWORD` must not be the bootstrap sentinel and must be >= 12 characters
- `TRUSTED_HOSTS` must be configured (non-empty)

Violations crash the server immediately with a descriptive error.

`docker-compose.yml` reinforces this with required environment variable syntax (`${SECRET_KEY?Set SECRET_KEY}`), failing at container startup if any are unset.

## Infrastructure Security

### Docker

- **Multi-stage build** (`Dockerfile`): frontend build stage is discarded; production image contains only runtime dependencies
- **Non-root user**: application runs as `agblogger` (created via `useradd`), not root
- **Volume ownership**: `/data/content` and `/data/db` are owned by the `agblogger` user
- **Health check**: `curl -f http://localhost:8000/api/health` every 30s with 3 retries
- **Internal-only exposure**: `docker-compose.yml` uses `expose: 8000` (not `ports`); only Caddy publishes to the host

### Caddy Reverse Proxy

- Automatic HTTPS with Let's Encrypt certificate issuance and renewal
- Host ports bound to `127.0.0.1` by default (not publicly accessible without explicit override)
- Static asset caching with `Cache-Control: immutable`
- Response compression (gzip + zstd)

### API Documentation

OpenAPI docs (`/docs`, `/redoc`, `/openapi.json`) are disabled in production by default. Enabled only when `debug=True` or `expose_docs=True`.

## Sync Integrity

The bidirectional sync protocol (`backend/services/sync_service.py`) uses SHA-256 file hashing for change detection, making it immune to clock skew. Three-way comparison (client manifest, server manifest, server current state) detects conflicts including `CONFLICT` and `DELETE_MODIFY_CONFLICT`. Front matter merges use `git merge-file` for semantic three-way body merging. The content directory is backed by a git repository for full change history.

## Static Analysis and Dependency Scanning

The quality gate (`just check`) includes multiple security-focused tools:

| Tool | Scope | What it catches |
|------|-------|-----------------|
| ruff (S rules) | Python | flake8-bandit security checks |
| Semgrep | Python, TypeScript, Docker | SAST with OWASP, secrets, supply-chain rules |
| pip-audit | Python deps | Known CVEs in Python packages |
| npm audit | JS deps | Known CVEs in npm packages |
| Trivy | Full repo | Vulnerabilities, misconfigurations, secrets, licenses |
| Checkov | Dockerfile, Compose | IaC misconfiguration analysis for container build/deploy manifests |
| Gitleaks | Git repo except `tests/` | Secret scanning over repository history with test fixture allowlist |
| Gitleaks (full) | Full git repo | Repository secret scan using Gitleaks' built-in default rules, bypassing the repo allowlist; kept in `just check-noisy` because fixtures intentionally trigger detections |
| CodeQL | Python, JS | Semantic code analysis (in `just check-extra`) |
| Snyk OSS | Python, JS manifests | Dependency vulnerability scanning (in `just check-extra`) |
| Snyk Code | Python, JS source | SAST via `just check-snyk` |
| Vulture | Python | Dead code that may indicate security-relevant remnants |
| mypy + basedpyright | Python | Strict type checking reduces type-confusion bugs |

Custom Semgrep rules (`.semgrep.yml`) block `eval()` and `new Function()` in JavaScript/TypeScript. Ruff's bandit rules are selectively relaxed only for pandoc/git subprocess invocations and test fixtures.

### Semgrep Rule Exclusions

The following Semgrep rules are excluded in the quality gate (`justfile:check-semgrep`) with documented justification:

| Excluded Rule | Justification |
|---------------|---------------|
| `react-dangerouslysetinnerhtml` (security.audit variant) | All `dangerouslySetInnerHTML` usages render Pandoc HTML that is sanitized server-side through the allowlist sanitizer (`_HtmlSanitizer` in `backend/pandoc/renderer.py`). The sanitizer strips all unsafe tags, validates URL schemes, and escapes attribute values. See [HTML Sanitization](#html-sanitization) above. |
| `react-dangerouslysetinnerhtml-prop` (prop variant) | Same justification as above — different Semgrep rule ID for the same pattern. |

**Affected files:** `PostCard.tsx`, `PostPage.tsx`, `SearchPage.tsx`, `EditorPage.tsx`, `AdminPage.tsx`, `PageViewPage.tsx`. These components render post content, excerpts, and page content that originates from the Pandoc rendering pipeline, which sanitizes all output before storage.
