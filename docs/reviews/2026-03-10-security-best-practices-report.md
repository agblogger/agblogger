# Security Best Practices Review

## Executive Summary

I reviewed the AgBlogger backend, frontend, CLI, deployment helpers, architecture/security docs, and the project-specific FastAPI/React security guidance. The codebase already has strong baseline controls: cookie-based sessions with CSRF protection, refresh-token rotation, draft-content authorization, path-traversal protections, SSRF defenses for dynamic outbound destinations, encrypted stored OAuth credentials, strict security headers, and a good set of regression tests.

I did not find a critical or high-severity vulnerability in the current codebase. I found three security-relevant gaps worth fixing:

1. The Pandoc preview endpoint is available to any authenticated user even though the editing workflow is admin-only, which creates an avoidable authenticated denial-of-service surface.
2. Admin draft auto-save uses shared `localStorage` keys, which can leak unpublished content across account switches or shared browser profiles.
3. OAuth pending-state storage uses a single global fixed-size in-memory pool per provider, so any authenticated user can evict another user's in-flight OAuth state by spamming authorize requests.

## Review Scope

- Architecture and security docs reviewed:
  - `docs/arch/index.md`
  - `docs/arch/security.md`
  - `docs/arch/auth.md`
  - `docs/arch/backend.md`
  - `docs/arch/frontend.md`
  - `docs/arch/data-flow.md`
  - `docs/arch/sync.md`
  - `docs/arch/cross-posting.md`
  - `docs/arch/deployment.md`
  - `docs/guidelines/security.md`
- Security guidance reviewed:
  - `.codex/skills/security-best-practices/references/python-fastapi-web-server-security.md`
  - `.codex/skills/security-best-practices/references/javascript-typescript-react-web-frontend-security.md`
  - `.codex/skills/security-best-practices/references/javascript-general-web-frontend-security.md`
- Targeted validation run:
  - `uv run pytest -q tests/test_api/test_security_regressions.py tests/test_api/test_auth_hardening.py tests/test_services/test_ssrf.py`
  - Result: `91 passed in 66.10s`

## Medium Severity

### SBP-001: Authenticated non-admin users can access the expensive Pandoc preview service

- Severity: Medium
- Impact: Any authenticated account can repeatedly invoke markdown rendering and consume Pandoc/backend resources, even though the editing workflow itself is admin-only.
- Location:
  - `backend/api/render.py:33`
  - `backend/api/posts.py:385`
  - `backend/api/posts.py:626`
  - `backend/api/posts.py:713`
- Evidence:
  - `backend/api/render.py:33-37` protects `/api/render/preview` with `Depends(require_auth)`.
  - The actual post editing/write endpoints are admin-only in `backend/api/posts.py:385-390`, `backend/api/posts.py:626-635`, and `backend/api/posts.py:713-723`.
  - `backend/api/render.py:23` allows request bodies up to `500_000` characters, and there is no route-level rate limiting on preview requests.
- Why this matters:
  - Preview rendering invokes Pandoc, which is substantially more expensive than a normal metadata/API read.
  - In the current role model, ordinary authenticated users should not need editor-only render capability.
- Fix:
  - Change `/api/render/preview` to `Depends(require_admin)`, or add a dedicated editor capability if non-admin editing is planned.
  - Add rate limiting for preview requests if the endpoint must remain available to non-admin users.
- Mitigation:
  - Reverse-proxy request throttling can reduce abuse, but the authorization boundary should still be tightened in-app.
- False positive notes:
  - If the product intentionally plans non-admin editing soon, the role mismatch may be temporary, but the lack of rate limiting still leaves an avoidable abuse surface.

## Low Severity

### SBP-002: Draft auto-save stores unpublished content in shared `localStorage` keys

- Severity: Low
- Impact: Unsaved draft content can persist across logout/session changes and be exposed to another user of the same browser profile or to any same-origin script execution.
- Location:
  - `frontend/src/pages/EditorPage.tsx:59`
  - `frontend/src/hooks/useEditorAutoSave.ts:111`
  - `frontend/src/hooks/useEditorAutoSave.ts:160`
- Evidence:
  - `frontend/src/pages/EditorPage.tsx:59` uses keys based only on post path, with new drafts stored under the global key `agblogger:draft:new`.
  - `frontend/src/hooks/useEditorAutoSave.ts:111-117` writes the full draft payload (`title`, `body`, `labels`, `isDraft`, `savedAt`) to `localStorage`.
  - `frontend/src/hooks/useEditorAutoSave.ts:160-167` removes the same shared key only on discard/save, so abandoned drafts persist indefinitely.
- Why this matters:
  - Drafts are often more sensitive than published content.
  - Because the key is not user-scoped, a different account on the same workstation/browser profile can inherit another editor's saved draft prompt.
  - `localStorage` is also accessible to any script that executes under the origin.
- Fix:
  - Namespace draft keys by user ID or username at minimum.
  - Prefer `sessionStorage` or encrypted server-side draft storage for unpublished admin content.
  - Add a logout hook to clear editor draft storage for the active user.
- Mitigation:
  - If local draft persistence must remain, display a warning that recovery data is browser-local and shared per browser profile.
- False positive notes:
  - This is primarily a privacy/confidentiality issue on shared endpoints or after any same-origin script compromise; it is less significant on a strictly single-user workstation.

### SBP-003: OAuth state storage uses a global fixed-size pool that allows user-to-user eviction

- Severity: Low
- Impact: Any authenticated user can invalidate another user's in-progress OAuth flow by filling the shared pending-state store until older entries are evicted.
- Location:
  - `backend/crosspost/bluesky_oauth_state.py:18`
  - `backend/crosspost/bluesky_oauth_state.py:23`
  - `backend/api/crosspost.py:279`
  - `backend/api/crosspost.py:437`
  - `backend/api/crosspost.py:626`
  - `backend/api/crosspost.py:767`
- Evidence:
  - `OAuthStateStore` is initialized with `max_entries=100` and evicts the oldest entry whenever the store is full (`backend/crosspost/bluesky_oauth_state.py:18-29`).
  - The authorize endpoints for Bluesky, Mastodon, X, and Facebook are available to any authenticated user and unconditionally add new state entries (`backend/api/crosspost.py:279-332`, `437-540`, `626-674`, `767-812`).
- Why this matters:
  - This is a straightforward authenticated denial-of-service primitive against other users' OAuth completion flow.
  - The issue is more relevant in a multi-user deployment with invites/self-registration enabled.
- Fix:
  - Enforce per-user limits instead of one global eviction pool.
  - Add per-endpoint rate limiting for OAuth authorize requests.
  - Consider storing pending OAuth state in the database with user scoping and explicit expiry.
- Mitigation:
  - Reverse-proxy throttling helps, but application-level per-user quotas are the correct fix.
- False positive notes:
  - On a strictly single-admin deployment the practical risk is low, but the code currently allows broader authenticated use than that assumption.

## Strengths Observed

- Cookie auth uses `HttpOnly`, `SameSite=Strict`, and non-debug `Secure` cookies.
- CSRF protection is stateless and enforced centrally for unsafe cookie-authenticated API requests.
- Refresh tokens, PATs, and invite codes are stored hashed, not plaintext.
- Draft post access control is consistently enforced for both post reads and content-file delivery.
- Content and sync paths have layered traversal defenses.
- Active content types served from `/api/content/*` are forced to download with a restrictive per-response CSP.
- Cross-post OAuth credentials are encrypted at rest.
- SSRF controls for dynamic cross-post destinations validate both URL shape and resolved public IPs.
- Security regression coverage is materially better than average for a project of this size.

## Residual Risks / Gaps Not Fully Reviewed at Runtime

- I did not perform a live browser-based or deployed DAST run in this review.
- I did not run the full `just check` gate; I ran targeted security-focused pytest suites instead.
- Multi-process/runtime behavior for in-memory security components (`OAuthStateStore`, rate limiting) should be verified if the app is ever deployed with multiple workers.
