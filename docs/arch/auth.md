# Authentication and Authorization

## Identity Model

AgBlogger supports two access patterns:

- **browser sessions** for the web UI
- **token-based access** for CLI and automation workflows

Browser auth is cookie-based so long-lived credentials do not live in readable frontend storage.

## Credential Boundaries

Passwords and long-lived credentials are stored as hashes. Browser sessions use short-lived access credentials with server-managed refresh behavior, while personal access tokens provide a separate path for non-browser clients. This separates interactive browser identity from automation use cases without pushing durable secrets into the SPA.

## Authorization Model

Authorization is enforced at the API boundary with a small role model:

- public readers can access published content
- authenticated users can perform account-scoped actions
- admins can mutate shared site content and administrative settings

Some content also carries an ownership boundary. Draft content is not public, and user-scoped features such as connected social accounts remain isolated to the owning user even though broader editorial workflows stay admin-led.

Frontend caches for reads whose response depends on the current browser user, including draft-only content and user-scoped account data, are scoped to the current browser user identity so session changes force revalidation instead of reusing stale authorized responses.

## Registration Posture

The default operating model is a closed, self-hosted deployment. Registration is admin-controlled, invite flows are available, and rate limiting protects authentication endpoints from abuse.

## Bootstrap

The backend can bootstrap an initial admin account from environment configuration during startup. Post metadata stores author identity in a durable content-friendly form, while presentation layers resolve richer profile information when content is read.

## Code Entry Points

- `backend/api/auth.py` exposes the authentication and account-management endpoints.
- `backend/api/deps.py` contains the shared authentication and authorization dependencies used across the API.
- `backend/services/auth_service.py` contains the core credential, token, invite, and profile logic.
- `frontend/src/api/auth.ts` and `frontend/src/stores/authStore.ts` implement the browser-side session integration.
