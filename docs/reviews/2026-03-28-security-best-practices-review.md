# Security Best Practices Review

**Date:** 2026-03-28
**Scope:** Security review of current branch changes against `origin/main`

## Executive Summary

I found two medium-severity regressions and one low-severity issue in the reviewed diff.

- The branch makes search and label reads draft-aware for authenticated admins, but the frontend does not consistently scope or clear the resulting client-side state on logout/session changes.
- `PATCH /api/auth/me` now returns internal rollback/repair details to clients on server-side failure paths instead of a generic internal-error message.

No high- or critical-severity issues were identified in the reviewed auth, session, draft-visibility, analytics, or deployment changes.

## Medium

### SBP-01: Draft search results can remain visible after logout in the current tab

- **Severity:** Medium
- **Rule IDs:** REACT-AUTH-SESSION-SCOPING, FASTAPI-AUTH-001
- **Impact:** A user who gets access to the browser tab after logout can still read draft titles/excerpts that were fetched while the admin was authenticated.
- **Evidence:**
  - The search API now includes drafts whenever an authenticated admin is present: `backend/api/posts.py:231-239`.
  - `SearchPage` stores results in local component state and only refreshes them when `query` changes, not when auth state changes: `frontend/src/pages/SearchPage.tsx:14-16`, `frontend/src/pages/SearchPage.tsx:30-49`.
  - The header search dropdown likewise keeps `dropdownResults` in local state, and `handleLogout()` does not clear it before logging out: `frontend/src/components/layout/Header.tsx:29-35`, `frontend/src/components/layout/Header.tsx:139-141`.
- **Why this is a problem:** Before this branch, `/api/posts/search` was public-only and did not return drafts. After the backend change, previously safe cached/in-memory search UI state became security-sensitive, but the frontend still treats it as ordinary public data.
- **Recommended fix:** Clear search state on logout/auth changes, or key search UI state to the current authenticated session and re-run/fail closed when auth changes.

### SBP-02: Draft-only label data is cached under global SWR keys and can persist across logout

- **Severity:** Medium
- **Rule IDs:** REACT-AUTH-SESSION-SCOPING, FASTAPI-AUTH-001
- **Impact:** Draft-only labels, post counts, and graph relationships can remain visible in the SPA after logout or session expiry until the cache is invalidated or the page is refreshed.
- **Evidence:**
  - Label endpoints now include draft data whenever an authenticated admin is present:
    - `backend/api/labels.py:92-98`
    - `backend/api/labels.py:101-107`
    - `backend/api/labels.py:238-245`
    - `backend/api/labels.py:251-266`
  - `useLabels()` still uses a global SWR key with no session scoping: `frontend/src/hooks/useLabels.ts:5-6`.
  - `useLabelGraph()` also uses a global SWR key with no session scoping: `frontend/src/hooks/useLabelGraph.ts:5-6`.
  - By contrast, `useLabelPosts()` already keys its SWR cache by `userId`, which is the safer pattern for auth-sensitive reads: `frontend/src/hooks/useLabelPosts.ts:12-19`.
- **Why this is a problem:** This branch changed formerly public label metadata into auth-dependent data, but two of the consuming hooks still cache it as if it were identical for logged-in and logged-out sessions.
- **Recommended fix:** Include `user?.id` or another session discriminator in the SWR keys for label/graph reads, and/or clear those SWR entries on logout.

## Low

### SBP-03: Profile update now returns internal rollback/repair details to clients

- **Severity:** Low
- **Rule IDs:** FASTAPI-ERR-001
- **Impact:** Internal failure details about rollback success and required operator intervention are exposed to clients on a server-side error path.
- **Evidence:**
  - `PATCH /api/auth/me` returns `"automatic rollback also failed — manual intervention required"` on filesystem/cache-rebuild failure paths: `backend/api/auth.py:441-460`.
- **Why this is a problem:** Project guidance says internal server errors should return generic messages to clients while detailed repair information stays in server logs. This message exposes operational state that is not needed by the client.
- **Recommended fix:** Return a generic `500` detail such as `"Failed to update profile"` and keep the rollback/manual-intervention specifics in logs only.

## High

No findings.

## Critical

No findings.
