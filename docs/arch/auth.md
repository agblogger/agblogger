# Authentication and Authorization

## Identity Model

AgBlogger uses cookie-based browser sessions for the web UI and short-lived bearer tokens for CLI and automation workflows (via the token-login endpoint).

## Credential Boundaries

Passwords are stored as bcrypt hashes. Browser sessions use short-lived JWT access tokens with server-managed refresh token rotation. The token-login endpoint issues short-lived bearer tokens for non-browser clients such as the sync CLI.

## Authorization Model

Authorization is enforced at the API boundary with a small role model:

- public readers can access published content
- authenticated users can perform account-scoped actions
- admins can mutate shared site content and administrative settings

Some content also carries an ownership boundary. Draft content is not public, and user-scoped features such as connected social accounts remain isolated to the owning user even though broader editorial workflows stay admin-led.

Frontend caches for reads whose response depends on the current browser user, including draft-only content and user-scoped account data, are scoped to the current browser user identity so session changes force revalidation instead of reusing stale authorized responses.

## Registration Posture

The system is a closed, single-admin deployment. User accounts are managed by the admin. Rate limiting protects authentication endpoints from abuse.

## Bootstrap

The backend bootstraps an initial admin account from environment configuration during startup. Post metadata stores author identity in a durable content-friendly form, while presentation layers resolve richer profile information when content is read.

## Code Entry Points

- `backend/api/auth.py` exposes the authentication and account-management endpoints.
- `backend/api/deps.py` contains the shared authentication and authorization dependencies used across the API.
- `backend/services/auth_service.py` contains the core credential, token, and profile logic.
- `frontend/src/api/auth.ts` and `frontend/src/stores/authStore.ts` implement the browser-side session integration.
