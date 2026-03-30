# Authentication and Authorization

## Identity Model

AgBlogger uses cookie-based sessions for the web UI and for the interactive sync CLI. Browser clients and the sync CLI both rely on refresh-token rotation to survive access-token expiry. The token-login endpoint exists for non-browser automation that needs an explicit short-lived bearer token.

## Credential Boundaries

Passwords are stored as bcrypt hashes. Session-based clients use short-lived JWT access tokens with server-managed refresh token rotation and a CSRF token derived from the current access token. The token-login endpoint issues short-lived bearer tokens for non-browser automation clients that manage their own reauthentication.

## Authorization Model

Authorization is enforced at the API boundary with a simple two-level model:

- public readers can access published content
- the authenticated admin can perform all actions (content mutation, site administration, cross-posting)

There is only one user: the admin. Every authenticated user is the admin — there is no separate role or multi-user model. Draft content is only visible to the authenticated admin.

## Auth-Sensitive Caching

Frontend caches for reads whose response depends on admin authentication, including draft-only content and admin-scoped account data, are scoped by user identity in the cache key, so auth state changes force revalidation instead of reusing stale authorized responses.

Backend read endpoints whose payload changes when admin authentication is present mark responses as auth-sensitive at the HTTP layer so draft-bearing JSON is not shared by intermediaries.

## Admin Bootstrap

AgBlogger is a closed, single-admin deployment with no registration flow. The admin account is bootstrapped from environment configuration during startup, and durable auth state is converged to a single live admin identity before the app begins serving requests.

## Code Entry Points

- `backend/api/auth.py` exposes the authentication and account-management endpoints.
- `backend/api/deps.py` contains the shared authentication and authorization dependencies used across the API.
- `backend/services/auth_service.py` contains the core credential, token, and profile logic.
- `frontend/src/api/auth.ts` and `frontend/src/stores/authStore.ts` implement the browser-side session integration.
