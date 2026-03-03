# Security Best Practices Review

## Executive Summary

I found six security issues in the current codebase. There are no obvious RCE-class bugs or unauthenticated admin takeovers in the reviewed paths, but there are two confirmed high-severity draft-content exposure bugs in the content-serving path. Both allow unauthenticated users to fetch draft assets under realistic workflows. I also found session-rotation gaps around password changes, unnecessary token exposure to browser JavaScript, a site-wide authorization weakness on label mutation, and an inconsistent admin password policy.

`SBP-001` and `SBP-002` were reproduced by running a temporary targeted regression test via `uv run pytest -q` during this review. The temporary test file was removed afterward.

## High Severity

### SBP-001: Renamed draft posts leak assets through the backward-compat symlink path

- Rule ID: SBP-001
- Severity: High
- Location: `backend/api/posts.py:657`, `backend/api/posts.py:668`, `backend/api/content.py:71`, `backend/api/content.py:77`, `backend/api/content.py:84`, `backend/api/content.py:113`
- Evidence:
  - `update_post_endpoint()` renames the post directory and creates a symlink from the old directory name to the new one in `backend/api/posts.py:657-689`.
  - `serve_content_file()` resolves symlinks before serving the file in `backend/api/content.py:113-129`.
  - `_check_draft_access()` authorizes draft assets by querying `PostCache.file_path.startswith(dir_prefix)` using the originally requested path prefix in `backend/api/content.py:71-85`.
  - After a rename, the cache row moves to the new prefix, so requests using the old symlink prefix no longer match any draft row and the function returns without enforcing access control.
- Impact: Anyone who knows or guesses the old slug can fetch assets from a renamed draft post without authentication.
- Fix: Canonicalize the requested content path to the resolved in-repo relative path before draft authorization, or drive the authorization lookup from the resolved file path instead of the raw request path. Add a regression test covering renamed draft assets through the old symlink path.
- Mitigation: Until fixed, avoid renaming draft posts that contain sensitive assets, or remove backward-compat symlinks for draft posts.
- False positive notes: Not speculative. I reproduced this and observed unauthenticated `GET /api/content/posts/<old-slug>/secret.txt` returning `200`.

### SBP-002: Deleting a directory-backed draft without `delete_assets=true` leaves its assets public

- Rule ID: SBP-002
- Severity: High
- Location: `backend/api/posts.py:702`, `backend/api/posts.py:709`, `backend/filesystem/content_manager.py:179`, `backend/filesystem/content_manager.py:194`, `backend/filesystem/content_manager.py:209`, `backend/api/content.py:84`
- Evidence:
  - `delete_post_endpoint()` defaults `delete_assets` to `False` in `backend/api/posts.py:709`.
  - `ContentManager.delete_post()` only removes `index.md` unless `delete_assets=True` in `backend/filesystem/content_manager.py:179-210`.
  - Draft asset access is denied only when `_check_draft_access()` finds a matching draft `PostCache` row in `backend/api/content.py:71-85`.
  - Once the post row is deleted, orphaned assets under `posts/<slug>/` are treated as public content.
- Impact: Sensitive draft assets remain internet-accessible after an admin deletes the draft post unless they explicitly choose full asset deletion.
- Fix: For draft posts, either force `delete_assets=True`, or preserve an access-control marker until the directory is removed. At minimum, make secure deletion the default for directory-backed drafts and add a regression test for orphaned draft assets.
- Mitigation: Operationally, always delete directory-backed drafts with `delete_assets=true`.
- False positive notes: Not speculative. I reproduced this and observed unauthenticated `GET /api/content/posts/<slug>/secret.txt` returning `200` after deleting only `index.md`.

## Medium Severity

### SBP-003: Password changes do not revoke existing refresh tokens or PATs

- Rule ID: SBP-003
- Severity: Medium
- Location: `backend/api/admin.py:197`, `backend/api/admin.py:210`, `backend/api/admin.py:212`, `backend/models/user.py:52`, `backend/models/user.py:68`, `backend/schemas/auth.py:72`
- Evidence:
  - `change_password()` in `backend/api/admin.py:197-213` updates only `user.password_hash` and commits.
  - The application has long-lived refresh tokens and PATs modeled in `backend/models/user.py:52-84`.
  - There is no refresh-token deletion or PAT revocation in the password-change path.
- Impact: If an attacker already stole a refresh token or PAT, changing the password does not remove their access.
- Fix: Revoke all refresh tokens for the user when the password changes, and either revoke PATs automatically or require explicit PAT rotation with a clear warning in the UI.
- Mitigation: After a password change, manually revoke all PATs and force logout on all sessions until automatic revocation exists.
- False positive notes: None. The absence of revocation is explicit in the current code path.

### SBP-004: Cookie-auth endpoints still hand access and refresh tokens to browser JavaScript

- Rule ID: SBP-004
- Severity: Medium
- Location: `backend/schemas/auth.py:31`, `backend/api/auth.py:191`, `backend/api/auth.py:315`, `frontend/src/api/auth.ts:4`, `frontend/src/api/client.ts:63`
- Evidence:
  - `TokenResponse` includes `access_token` and `refresh_token` in `backend/schemas/auth.py:31-37`.
  - `/api/auth/login` and `/api/auth/refresh` both set HttpOnly cookies and also return the tokens in JSON in `backend/api/auth.py:191-197` and `backend/api/auth.py:315-319`.
  - The frontend parses these responses in normal browser code in `frontend/src/api/auth.ts:4-7` and `frontend/src/api/client.ts:63-71`.
- Impact: Any XSS or malicious same-origin script can exfiltrate the refresh token despite the cookie transport being marked HttpOnly, weakening the main benefit of cookie-based session storage.
- Fix: For browser flows, keep tokens cookie-only and return only the CSRF token plus any non-sensitive session metadata. If CLI support is needed, split it into a separate endpoint or auth mode.
- Mitigation: Keep CSP and sanitization strict, and minimize token lifetime until the API contract is tightened.
- False positive notes: If the same endpoint must support non-browser clients, the safer fix is transport separation, not keeping both token delivery modes enabled together.

### SBP-005: Any authenticated user can modify site-wide label configuration

- Rule ID: SBP-005
- Severity: Medium
- Location: `backend/api/labels.py:100`, `backend/api/labels.py:106`, `backend/api/labels.py:141`, `backend/api/labels.py:148`, `backend/api/labels.py:188`, `backend/api/labels.py:194`
- Evidence:
  - Label create/update/delete endpoints mutate the shared `labels.toml` source of truth and commit those changes.
  - Those endpoints are protected with `require_auth`, not `require_admin`, in `backend/api/labels.py`.
- Impact: Any authenticated account can alter global taxonomy, navigation, and label relationships for the whole site.
- Fix: Require admin privileges for label mutation, or introduce an explicit scoped editor role if collaborative taxonomy editing is intended.
- Mitigation: Keep self-registration disabled and tightly control who receives accounts until authorization is narrowed.
- False positive notes: If every authenticated user is intentionally a trusted site maintainer, this may be by design. The current architecture docs do not clearly document that trust model.

## Low Severity

### SBP-006: Admin password changes allow weaker passwords than the rest of the system

- Rule ID: SBP-006
- Severity: Low
- Location: `backend/schemas/admin.py:70`, `backend/schemas/auth.py:26`, `backend/config.py:97`
- Evidence:
  - `PasswordChange.new_password` and `confirm_password` accept 8-character passwords in `backend/schemas/admin.py:70-75`.
  - Registration requires 12 characters in `backend/schemas/auth.py:26`.
  - Production bootstrap enforcement also requires 12 characters in `backend/config.py:97-98`.
- Impact: A privileged user can rotate into a password that would be rejected everywhere else, weakening the admin account unnecessarily.
- Fix: Raise the admin password-change minimum to 12 characters and keep frontend validation in sync.
- Mitigation: Document and enforce the stronger policy operationally until the schema is aligned.
- False positive notes: None.
