# Security Best Practices Review

Date: March 3, 2026

## Executive Summary

AgBlogger's core authn/authz posture is materially stronger than average for a self-hosted app: cookie sessions are `HttpOnly` + `SameSite=Strict`, CSRF is implemented, draft access checks are deliberate, host/origin hardening exists, and cross-post SSRF protections are present in the OAuth/Mastodon/Bluesky paths.

I found 3 actionable issues worth prioritizing:

1. A plaintext fallback in cross-post credential handling defeats the documented "encrypted at rest" guarantee.
2. Uploaded/synced assets are served same-origin with active content types intact, which can bypass the markdown sanitizer and become stored XSS.
3. Multipart endpoints have only post-parse size checks; the repo-visible deployment config does not enforce request-body limits at the edge.

## Medium Severity

### SBP-001: Cross-post credential decryption fails open to plaintext JSON

- Severity: Medium
- Location:
  - `backend/services/crosspost_service.py:197`
  - `backend/services/crosspost_service.py:214`
  - `tests/test_services/test_crosspost_decrypt_fallback.py:38`
  - `tests/test_services/test_crosspost_decrypt_fallback.py:70`
- Evidence:
  - The service first tries `json.loads(decrypt_value(account.credentials, secret_key))`.
  - If that fails, it falls back to `json.loads(account.credentials)`, which accepts plaintext JSON stored directly in the database.
  - The regression test explicitly inserts unreadable/non-encrypted credential content and asserts the fallback path is used instead of failing closed.
- Impact:
  - This bypasses the app's stated "credentials encrypted at rest" control. Any plaintext rows remain usable indefinitely, and a DB exposure reveals live third-party OAuth/API tokens without needing `SECRET_KEY`.
- Fix:
  - Remove the plaintext fallback from request-time credential handling.
  - Add a one-time migration or admin repair command to re-encrypt legacy rows explicitly.
  - On decryption failure, fail closed and require the account to be reconnected.
- Mitigation:
  - Until fixed, audit the `social_accounts.credentials` column for plaintext JSON rows and re-encrypt them offline.
- False positive notes:
  - If the database never contains plaintext rows, exploitation requires either legacy data or direct DB tampering. The security weakness is still real because the code intentionally preserves the bypass.

### SBP-002: Uploaded and synced assets can be served as same-origin active content

- Severity: Medium
- Location:
  - `backend/api/posts.py:236`
  - `backend/api/posts.py:301`
  - `backend/api/posts.py:398`
  - `backend/api/posts.py:417`
  - `backend/api/sync.py:239`
  - `backend/api/sync.py:337`
  - `backend/api/content.py:128`
  - `backend/api/content.py:133`
- Evidence:
  - Post upload writes every non-markdown file into the public post directory with only basename normalization.
  - Asset upload accepts any filename except dotfiles and writes bytes directly.
  - Sync commit writes arbitrary uploaded files under `content/`.
  - The content-serving endpoint guesses MIME type and returns `FileResponse` inline; it does not block or force-download HTML, SVG, JS, or other active content.
- Impact:
  - A malicious `.html` asset plus same-directory `.js` payload, or certain active formats such as SVG, can execute under the blog's origin when visited directly. That bypasses the markdown sanitizer entirely and can be used for stored XSS or authenticated action abuse against an admin browsing the site.
- Fix:
  - Treat user/content assets as untrusted and allowlist safe passive types only.
  - At minimum, force dangerous types (`text/html`, `image/svg+xml`, JS, XML, PDF with script support, etc.) to download with `Content-Disposition: attachment`.
  - Better: serve untrusted assets from a separate origin with no cookies and a restrictive CSP.
- Mitigation:
  - If arbitrary asset types must remain supported, isolate them onto a cookieless asset host and do not allow them to share the main app origin.
- False positive notes:
  - This is lower risk if only a fully trusted admin ever writes content. It becomes materially more important if content arrives through sync, imports, shared repos, or third-party contributions.

### SBP-003: Multipart endpoints rely on post-parse limits; no edge request-body cap is visible

- Severity: Medium
- Location:
  - `backend/api/posts.py:221`
  - `backend/api/posts.py:250`
  - `backend/api/posts.py:377`
  - `backend/api/posts.py:405`
  - `backend/api/sync.py:168`
  - `backend/api/sync.py:176`
  - `backend/api/sync.py:249`
  - `backend/api/sync.py:253`
  - `Caddyfile:18`
  - `Caddyfile:38`
- Evidence:
  - Upload endpoints use FastAPI multipart parameters (`UploadFile`, `File(...)`).
  - File-size checks happen only after request parsing and after route entry via `await upload_file.read(...)`.
  - The checked-in Caddy config shows caching/compression directives but no request-body size limit.
- Impact:
  - An attacker can still force the server/proxy to accept and parse very large multipart bodies before the application returns `413`. That creates avoidable CPU, memory, disk-spool, and connection-exhaustion risk on upload paths.
- Fix:
  - Enforce request-body size caps at the reverse proxy for upload routes.
  - Keep the in-app per-file/per-request limits as a second layer.
  - Consider tighter endpoint-specific limits for `/api/posts/upload`, `/api/posts/*/assets`, and `/api/sync/commit`.
- Mitigation:
  - If a different ingress already enforces request limits, document the exact cap and keep it aligned with the app-level expectations.
- False positive notes:
  - This may already be handled by infrastructure not visible in this repo. I did not see a repo-local edge limit in `Caddyfile`.

## Positive Controls Observed

- Cookie sessions use `HttpOnly`, `SameSite=Strict`, and `Secure` outside debug: `backend/api/auth.py:57`
- CSRF protection is enforced in middleware for unsafe cookie-authenticated API requests: `backend/main.py:308`
- Login origin enforcement and browser rejection for token-login are implemented: `backend/api/auth.py:109`, `backend/api/auth.py:127`
- Draft post and draft asset access checks are explicit and return `404` to non-owners: `backend/api/content.py:57`, `backend/api/posts.py:425`
- Host-header validation and CSP/security headers are enabled in the app stack: `backend/main.py:302`, `backend/main.py:340`
- SSRF-hardened outbound HTTP handling exists for the most attacker-influenced remote targets: `backend/crosspost/ssrf.py:1`, `backend/crosspost/mastodon.py:64`, `backend/crosspost/atproto_oauth.py:315`

## Recommended Remediation Order

1. Remove the plaintext credential fallback and migrate any legacy `social_accounts.credentials` rows.
2. Block or isolate active content types from `/api/content/*`.
3. Add reverse-proxy request-body limits for all multipart endpoints.
