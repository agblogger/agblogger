# Security Best Practices Review

**Date:** 2026-03-27
**Scope:** Security review of changes on the current branch against `origin/main`

## Executive Summary

One medium-severity issue was found in the single-admin refactor: the codebase now documents and models AgBlogger as a single-admin system, but the migration/bootstrap path still allows multiple legacy admin accounts to remain valid. This weakens admin-credential rotation and can leave stale admin credentials usable indefinitely after migration or `ADMIN_USERNAME` changes.

No additional critical or high-severity regressions were identified in the reviewed auth, session, draft-visibility, analytics, and deployment changes.

## Medium

### M-01: Single-admin migration/bootstrap does not enforce a single valid admin account

- **Rule ID:** FASTAPI-AUTH-001
- **Severity:** Medium
- **Location:** `backend/migrations/versions/0004_rename_admin_tables_drop_is_admin.py:62`, `backend/services/auth_service.py:80`, `backend/services/auth_service.py:206`
- **Evidence:**
  - `backend/migrations/versions/0004_rename_admin_tables_drop_is_admin.py:62-89` deletes only `is_admin = 0` users, then renames `users` to `admin_users`. Any legacy `is_admin = 1` rows survive the migration.
  - `backend/services/auth_service.py:214-215` explicitly documents that changing `ADMIN_USERNAME` creates a new admin account "alongside the old one".
  - `backend/services/auth_service.py:84-93` authenticates any `AdminUser` row whose username/password match.
- **Impact:** Old admin credentials can keep full admin access after a migration to the single-admin model or after an operator changes `ADMIN_USERNAME`, defeating the expectation that there is only one active admin identity.
- **Fix:** Enforce a single admin row during migration/bootstrap. Either fail fast when multiple admin rows exist, or deterministically collapse to the configured admin identity and revoke/delete all other admin rows plus their refresh tokens.
- **Mitigation:** Until fixed, treat `ADMIN_USERNAME` changes as non-revocative and manually audit the `admin_users` table after migration or username rotation.
- **False positive notes:** If the deployment has never had more than one admin-capable row and `ADMIN_USERNAME` has never changed, the issue may not be reachable in practice.

## High

No findings.

## Critical

No findings.

## Low / Informational

No additional findings in the reviewed diff.

## Reviewed Areas

- Auth/session flow: `backend/api/auth.py`, `backend/api/deps.py`, `backend/services/auth_service.py`
- Draft visibility and content serving: `backend/api/posts.py`, `backend/api/content.py`, `backend/services/post_service.py`, `backend/services/label_service.py`
- Analytics auth boundary: `backend/api/analytics.py`, `backend/services/analytics_service.py`
- Runtime/deployment hardening: `backend/main.py`, `backend/config.py`, `Dockerfile`, `docker-compose.yml`, `cli/deploy_production.py`
