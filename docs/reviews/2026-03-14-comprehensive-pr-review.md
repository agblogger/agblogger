# Comprehensive PR Review — Stress Testing Fixes

**Date:** 2026-03-14
**Scope:** 7 commits since origin/main (18 files changed, +371/-86)
**Reviewers:** 4 automated agents (code, errors, tests, comments)

## Commits Reviewed

- `5e9450d` docs: add stress testing prompt and report
- `c724087` fix: resolve 3 API issues found by stress testing
- `59b4cd0` fix: update nosemgrep rule IDs in PostCard to match current Semgrep rules
- `a39f837` fix dependencies
- `88461e5` fix: bump pyjwt to >=2.12 to resolve GHSA-752w-5fwx-jx9f
- `083fc6e` fix: return opaque 404 for all content path rejections
- `3b74497` fix: enable prefix matching in FTS5 search

## Critical Issues

### 1. Whitespace-only search query crashes FTS5

**Files:** `backend/services/post_service.py:271-272`
**Found by:** test-analyzer, error-reviewer, code-reviewer

A query like `" "` passes FastAPI's `min_length=1` but `query.split()` returns `[]`, producing an empty FTS5 MATCH string. This causes `OperationalError` from SQLite that propagates as an unhandled 500. Violates the "server may NEVER crash" guideline.

**Fix:** Guard for empty terms after splitting and return empty results.

### 2. Missing security logging for path traversal rejections

**Files:** `backend/api/content.py:43-63`
**Found by:** error-reviewer

The 404 unification is correct security posture, but no branch logs the rejection server-side. The project's `docs/guidelines/security.md` (line 227) requires logging path traversal attempts at WARNING level. The sync service (`backend/services/sync_service.py:485`) correctly logs these; the content endpoint does not.

**Fix:** Add a logger and log each rejection branch at WARNING before raising.

## Important Issues

### 3. `_resolve_symlink_redirect` swallows filesystem errors

**Files:** `backend/api/posts.py:634-653`
**Found by:** error-reviewer

`OSError` / `PermissionError` from `exists()`, `resolve()`, or `relative_to()` will propagate as unhandled 500s.

**Fix:** Wrap in `try/except OSError`, log at WARNING, return `None`.

### 4. `_resolve_symlink_redirect` lacks path traversal check

**Files:** `backend/api/posts.py:634-653`
**Found by:** error-reviewer, code-reviewer

The function probes `full_path.exists()` before the `is_relative_to` containment check, allowing existence probes of arbitrary paths. Inconsistent with the defensive pattern in `content.py`.

**Fix:** Reject `..` segments early, matching `_validate_path`'s pattern.

### 5. Stress testing report has factual inaccuracies

**Files:** `docs/reviews/2026-03-14-stress-testing.md:82-84, 109`
**Found by:** comment-analyzer

The report claims list responses show usernames, not display names. In reality, `post_service.py:30` uses `COALESCE(display_name, username)` for both list and detail responses, so display name changes take effect immediately. The request count estimate (8,000+) also undercounts the actual total (~18,000+).

**Fix:** Correct the report text.

## Suggestions

### 6. `_resolve_symlink_redirect` docstring should document security guard

**Files:** `backend/api/posts.py:634-653`
**Found by:** comment-analyzer

Add a note about the `is_relative_to` containment check so future maintainers don't weaken it.

### 7. `response_model=PostDetail` doesn't reflect `RedirectResponse` return

**Files:** `backend/api/posts.py:656`
**Found by:** code-reviewer

Works at runtime (FastAPI short-circuits for Response subclasses) but is misleading in OpenAPI docs. Can be addressed by adding `responses={301: {...}}` or using `response_model=None`.

### 8. Duplicate test coverage

**Files:** `tests/test_api/test_label_posts_404.py`
**Found by:** test-analyzer

Overlaps with `test_api_integration.py`'s `test_label_posts_nonexistent_label_returns_404`. The standalone test has value as a faster isolated check.

### 9. Page service comment could be more precise

**Files:** `backend/services/page_service.py:32`
**Found by:** comment-analyzer

"Virtual pages (timeline, labels, etc.)" could be "Pages without a backing file" to match the actual `file is None` condition.

## Strengths

- **404 unification** in `content.py` is excellent security hardening with a clear "why" comment
- **Label 404 fix** correctly addresses a real API inconsistency
- **Virtual page generalization** removes hardcoded `"timeline"` check cleanly
- **Test coverage** is thorough with property-based path safety tests
- **Symlink redirect comments** clearly document the failure hierarchy
- **PyJWT bump** addresses a real CVE consistently in both pyproject files
