# Authentication and Authorization

## Token and Session Flow

- **Web sessions**: `POST /api/auth/login` issues `access_token` and `refresh_token` as `HttpOnly` cookies and returns only a `csrf_token` in JSON.
- **Non-browser bearer login**: `POST /api/auth/token-login` returns a short-lived bearer `access_token` for CLI/tests/automation and does not set cookies.
- **CSRF protection**: Unsafe API methods (`POST/PUT/PATCH/DELETE`) with cookie auth require `X-CSRF-Token` matching a stateless token derived from the current access cookie. The frontend fetches that token from `GET /api/auth/csrf`, caches it in memory, and also receives fresh values from login/refresh responses.
- **Login origin enforcement**: Login requests with `Origin`/`Referer` must match the app origin or configured CORS origins.
- **Token-login browser rejection**: `token-login` rejects requests carrying `Origin` or `Referer`, forcing browsers onto the cookie session flow.
- **Access tokens**: Short-lived (15 min), HS256 JWT containing `{sub: user_id, username, is_admin}` and signed with a derived signing key rather than the raw application secret.
- **Refresh tokens**: Long-lived (7 days), cryptographically random 48-byte strings. Only SHA-256 hashes are stored in DB. Refresh rotates tokens and revokes the old one.
- **PATs (Personal Access Tokens)**: Long-lived random tokens (hashed in DB) for CLI/API automation via Bearer auth.
- **Passwords**: bcrypt hashed.
- **Password rotation**: Admin password changes require at least 12 characters and revoke all stored refresh tokens and personal access tokens for that user.
- **Logout**: `POST /api/auth/logout` revokes refresh token (if present) and clears auth cookies.
- **Trusted proxy handling**: `X-Forwarded-For` is only trusted when the direct peer IP is in `TRUSTED_PROXY_IPS`; otherwise the socket peer IP is used for rate-limit keys.

## Registration and Abuse Controls

- **Self-registration** is disabled by default (`AUTH_SELF_REGISTRATION=false`).
- **Invite-based registration** is enabled by default (`AUTH_INVITES_ENABLED=true`): admins generate single-use invite codes.
- **Rate limiting** is applied to failed auth attempts on login and refresh endpoints in a sliding window.

## Roles

| Role | Access |
|------|--------|
| Unauthenticated | Read published (non-draft) posts, labels, pages, search |
| Authenticated | Above + cross-post and user-scoped account actions |
| Admin | Above + post create/update/delete/upload/edit-data, label mutations, sync, and admin panel operations |

Public reads require no authentication. The `get_current_user()` dependency returns `None` for unauthenticated requests.

**Draft visibility**: Draft posts and their co-located assets are visible only to their author for read endpoints. The post listing endpoint filters drafts by `author_username`, a stable owner field stored in post front matter and cached in `PostCache`. Cache rebuilds and sync normalize older content by backfilling `author_username` when ownership can be resolved safely. Direct access to draft post pages and content files enforces the same owner-only restriction, including legacy flat draft markdown files under `posts/*.md`. Content authorization is based on the resolved canonical path, so renamed-directory symlinks cannot bypass draft checks. Deleting a directory-backed draft now removes its co-located assets even when `delete_assets=false`, preventing orphaned draft files from becoming public. Editing endpoints are admin-only regardless of draft owner.

## Admin Bootstrap

On startup, `ensure_admin_user()` creates the admin user from `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables if no matching user exists.
