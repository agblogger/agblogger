# Security Best Practices Review

**Date:** 2026-03-27
**Scope:** Security review of changes on the current branch against `origin/main`

## Executive Summary

No medium, high, or critical security regressions were identified in the reviewed auth, session, draft-visibility, analytics, and deployment changes. A finding raised during initial review (M-01) has been retracted as a false positive after closer inspection of the bootstrap code.

## Medium

### ~~M-01: Single-admin migration/bootstrap does not enforce a single valid admin account~~ — RETRACTED (False Positive)

- **Rule ID:** FASTAPI-AUTH-001
- **Original Severity:** Medium
- **Status:** Retracted. This finding was incorrect.

The `ensure_admin_user` function in `backend/services/auth_service.py` already enforces the single-admin invariant on every startup. It queries all `AdminUser` rows, collapses any stale admin identities into the configured admin account via `_collapse_admin_identities`, and revokes all refresh tokens for stale rows plus the active admin if the identity changed. The recommended fix ("deterministically collapse to the configured admin identity and revoke/delete all other admin rows plus their refresh tokens") is exactly what the code already does.

The only theoretical window where multiple admin rows could coexist is between the migration step and the `ensure_admin_user` call — but both run sequentially in the same startup sequence before the server begins accepting requests, so no requests can be served with stale credentials during that window.

The original evidence cited (`auth_service.py:214-215`) referred to a stale comment that no longer reflects the current implementation. The current code replaces any legacy username with the configured one rather than creating a new row alongside the old one.

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
