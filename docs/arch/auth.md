# Authentication and Authorization

## Identity Model

AgBlogger uses cookie-based browser sessions for the web UI and short-lived bearer tokens for CLI and automation workflows (via the token-login endpoint).

## Credential Boundaries

Passwords are stored as bcrypt hashes. Browser sessions use short-lived JWT access tokens with server-managed refresh token rotation. The token-login endpoint issues short-lived bearer tokens for non-browser clients such as the sync CLI.

## Authorization Model

Authorization is enforced at the API boundary with a simple two-level model:

- public readers can access published content
- the authenticated admin can perform all actions (content mutation, site administration, cross-posting)

There is only one user: the admin. Every authenticated user is the admin — there is no separate role or multi-user model. Draft content is only visible to the authenticated admin.

Frontend caches for reads whose response depends on admin authentication, including draft-only content and admin-scoped account data, are scoped to the current browser session, so session changes force revalidation instead of reusing stale authorized responses.

## Registration Posture

The system is a closed, single-admin deployment. The admin account is bootstrapped from environment configuration. There is no registration flow. Rate limiting protects authentication endpoints from abuse.

## Bootstrap

The backend bootstraps an initial admin account from environment configuration during startup. Post metadata stores author identity in a durable content-friendly form, while presentation layers resolve richer profile information when content is read.

## Code Entry Points

- `backend/api/auth.py` exposes the authentication and account-management endpoints.
- `backend/api/deps.py` contains the shared authentication and authorization dependencies used across the API.
- `backend/services/auth_service.py` contains the core credential, token, and profile logic.
- `frontend/src/api/auth.ts` and `frontend/src/stores/authStore.ts` implement the browser-side session integration.
