# Authentication & Authorization Security Review

**Date:** 2026-03-26
**Scope:** Authentication flows, authorization enforcement, draft visibility across all API endpoints

> **Note:** This review has been updated to reflect the single-admin model. Registration, invite codes, and personal access tokens (PATs) have been removed. All authenticated users are the admin; there is no multi-user model.

## Overall Assessment: Strong

The authentication and authorization implementation is thorough and follows security best practices. No exploitable security vulnerabilities were found.

## Strengths

### Authentication

- **Cookie hardening** (`backend/api/auth.py:74-80`): HttpOnly, SameSite=Strict, Secure (outside debug). Correctly implemented.
- **CSRF protection** (`backend/main.py:454-484`): Stateless CSRF tokens bound to access tokens, enforced on all unsafe methods to `/api/`, with timing-safe comparison via `secrets.compare_digest`.
- **Rate limiting** (`backend/api/auth.py:188-213`): Login and refresh endpoints are rate-limited per client IP + username.
- **Timing-safe auth** (`backend/services/auth_service.py:83-85`): Dummy bcrypt hash check for non-existent users prevents username enumeration via timing side channels.
- **Refresh token rotation** (`backend/services/auth_service.py:142-154`): One-time-use with atomic DELETE for race-condition protection under concurrency.
- **Credential hashing**: Refresh tokens stored as one-way hashes (SHA-256 for tokens, bcrypt for passwords).
- **Origin enforcement** (`backend/api/auth.py:126-141`): Browser login validates Origin/Referer against allowed origins.
- **Token-login separation** (`backend/api/auth.py:144-150`): Browser-originated requests blocked from Bearer token login endpoint.
- **Session revocation on password change** (`backend/api/admin.py:246`): All refresh tokens revoked when password is changed.

### Authorization

- All content mutation endpoints (`create`, `update`, `delete`, `upload`, `assets`, `render/preview`) properly use `require_admin`.
- Sync endpoints all use `require_admin`.
- Admin panel endpoints all use `require_admin`.
- Cross-posting endpoints use `require_admin`.

## Draft Visibility: Properly Enforced

Drafts are correctly hidden from public users across all read paths:

| Path | Mechanism | Location |
|------|-----------|----------|
| `GET /api/posts` (list) | `draft_owner_username` filter: shows published + admin's own drafts | `post_service.py:96-107` |
| `GET /api/posts/{path}` (detail) | Author-match check, returns `None` for non-authors | `post_service.py:263` |
| `GET /api/posts/search` | SQL filter `is_draft = 0` in FTS query | `post_service.py:297` |
| `GET /api/labels/{id}/posts` | Calls `list_posts` without `draft_owner_username` -> hides all drafts | `post_service.py:323-329` |
| `GET /api/content/{path}` | `_check_draft_access` returns 404 for non-author access to draft files | `content.py:75-125` |
| `GET /api/analytics/views/{path}` | Only resolves published posts (`is_draft.is_(False)`) | `analytics.py:72-74` |
| `GET /api/labels` (post counts) | Post counts filtered by draft visibility | `label_service.py:80-85` |
| Raw markdown content | Only available via `/edit` endpoint, which requires `require_admin` | `posts.py:409-413` |

**Information disclosure prevention**: Draft content files and draft posts return `404 Not Found` (not `403 Forbidden`) to prevent confirming post existence to unauthorized users.

## Endpoint Authorization Matrix

| Endpoint | Auth Requirement | Notes |
|----------|-----------------|-------|
| `POST /api/auth/login` | None (login) | Rate-limited, origin-checked |
| `POST /api/auth/token-login` | None (login) | Rate-limited, browser-blocked |
| `POST /api/auth/refresh` | Refresh token | Rate-limited, CSRF-protected |
| `POST /api/auth/logout` | Refresh token | CSRF-protected |
| `GET /api/auth/csrf` | Cookie session | |
| `GET /api/auth/me` | `get_current_admin` | |
| `PATCH /api/auth/me` | `require_admin` | |
| `GET /api/posts` | `get_current_admin` (optional) | Draft filtering applied |
| `GET /api/posts/search` | None | Drafts excluded in FTS query |
| `GET /api/posts/{path}` | `get_current_admin` (optional) | Draft filtering applied |
| `GET /api/posts/{path}/edit` | `require_admin` | |
| `POST /api/posts` | `require_admin` | |
| `PUT /api/posts/{path}` | `require_admin` | |
| `DELETE /api/posts/{path}` | `require_admin` | |
| `POST /api/posts/upload` | `require_admin` | |
| `POST/GET/DELETE/PATCH assets` | `require_admin` | |
| `GET /api/labels` | `get_current_admin` (optional) | Post counts filtered |
| `GET /api/labels/{id}` | `get_current_admin` (optional) | Post count filtered |
| `GET /api/labels/{id}/posts` | None | Drafts hidden (no user passed) |
| `POST/PUT/DELETE /api/labels` | `require_admin` | |
| `GET /api/pages` | None | Public site config |
| `GET /api/pages/{id}` | `get_current_admin` (optional) | Pages are always public |
| `GET/PUT /api/admin/site` | `require_admin` | |
| `GET/POST/PUT/DELETE /api/admin/pages` | `require_admin` | |
| `PUT /api/admin/password` | `require_admin` | Rate-limited |
| `GET/PUT /api/admin/analytics/settings` | `require_admin` | |
| `GET /api/admin/analytics/stats/*` | `require_admin` | |
| `GET /api/analytics/views/{path}` | None | Only resolves published posts |
| `POST /api/render/preview` | `require_admin` | |
| `POST/GET /api/sync/*` | `require_admin` | |
| `POST/GET/DELETE /api/crosspost/accounts` | `require_admin` | |
| `POST /api/crosspost/post` | `require_admin` | |
| `GET /api/crosspost/history/{path}` | `require_admin` | |
| OAuth authorize endpoints | `require_admin` | |
| OAuth callback endpoints | State token (anti-CSRF) | Standard OAuth pattern |
| `GET /api/content/{path}` | `get_current_admin` (optional) | Draft access checked |
| `GET /api/health` | None | No sensitive data |

## Minor Observations (Not Vulnerabilities)

### 1. `GET /api/labels/{id}/posts` doesn't pass `draft_owner_username`

**Location:** `backend/api/labels.py:254-265`

This endpoint does not inject `get_current_admin` and doesn't pass `draft_owner_username` to `get_posts_by_label`. As a result, even the admin can't see their own draft posts when filtering by label. This is a **feature gap**, not a security issue -- drafts are hidden (conservative default), they're just also hidden from the admin on this specific endpoint.

### 2. OAuth callbacks lack session authentication

**Location:** `backend/api/crosspost.py:364`, `573`, `708`, `847`

The OAuth callbacks from providers (Bluesky, Mastodon, X, Facebook) don't verify the current browser session matches `pending["user_id"]`. This is standard OAuth design -- the state parameter serves as the anti-forgery token, and PKCE binds the code exchange. The Facebook `select-page` and `pages` endpoints do verify `pending["user_id"] != user.id`, which is an additional check for the interactive step.

### 3. Health endpoint exposes version

**Location:** `backend/api/health.py:41`

`GET /api/health` returns the application version without authentication. This is typical for health checks but provides version fingerprinting to unauthenticated users. Low risk for a self-hosted platform.

## Files Reviewed

- `backend/api/deps.py` -- Auth dependencies (`get_current_admin`, `require_admin`)
- `backend/api/auth.py` -- Auth endpoints (login, refresh, logout, CSRF, profile)
- `backend/api/posts.py` -- Post CRUD and asset management endpoints
- `backend/api/content.py` -- Content file serving with draft access checks
- `backend/api/labels.py` -- Label endpoints with post count filtering
- `backend/api/admin.py` -- Admin panel endpoints
- `backend/api/pages.py` -- Public page endpoints
- `backend/api/analytics.py` -- Analytics admin and public view count endpoints
- `backend/api/render.py` -- Markdown preview endpoint
- `backend/api/sync.py` -- Sync protocol endpoints
- `backend/api/crosspost.py` -- Cross-posting and OAuth flow endpoints
- `backend/api/health.py` -- Health check endpoint
- `backend/main.py` -- CSRF middleware, security headers
- `backend/services/auth_service.py` -- Token creation, refresh rotation, credential verification
- `backend/services/csrf_service.py` -- Stateless CSRF token creation and validation
- `backend/services/post_service.py` -- Draft filtering in list, get, and search queries
- `backend/services/label_service.py` -- Draft-aware post count filtering
- `docs/arch/auth.md` -- Auth architecture documentation
- `docs/arch/security.md` -- Security architecture documentation
- `docs/guidelines/security.md` -- Security development guidelines
