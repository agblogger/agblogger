# Security Best Practices Review

## Executive Summary

Reviewed the changes in `HEAD` against `origin/main` with emphasis on the FastAPI backend routes and supporting tests. I found one security regression: the new renamed-post redirect logic discloses the canonical path of renamed draft posts to unauthenticated callers. I did not find a direct draft content exposure in the reviewed diff, but the redirect leaks draft existence and slug metadata and should be fixed before merge.

## High Severity

### SBP-001: Renamed draft posts now disclose their canonical path through a public 301 redirect

- Rule ID: `FASTAPI-AUTH-001`
- Severity: High
- Location:
  - `backend/api/posts.py:634-664`
  - `backend/api/posts.py:679-686`
- Evidence:
  - `get_post_endpoint()` first checks `get_post(...)` with draft filtering. When that returns `None`, it immediately falls back to `_resolve_symlink_redirect(file_path, content_manager)` and returns `RedirectResponse(url=f"/api/posts/{resolved}", status_code=301)`.
  - `_resolve_symlink_redirect()` resolves the old filesystem path and returns the canonical target path without checking whether the target post is a draft or whether the caller is allowed to see it.
- Impact:
  - Anyone who knows or guesses an old renamed draft URL can obtain a `301` redirect to the current canonical draft path, revealing that the draft exists and disclosing its current slug. Because `301` responses are cacheable by default, an authenticated request could also prime shared intermediaries to replay that disclosure to unauthenticated clients.
- Reproduction:
  1. Create a draft post.
  2. Rename it so the backend creates the backward-compatibility symlink.
  3. Request the old path without authentication.
  4. Observed result during review: `301 Location: /api/posts/posts/2026-03-14-draft-renamed/index.md`, followed by `404` when the redirect is followed.
- Why this violates project guidance:
  - `docs/arch/security.md` says draft content is non-public.
  - `docs/guidelines/security.md` requires draft content routes to return `404` instead of disclosing draft existence to non-authors.
- Fix:
  - Resolve the symlink target, then re-run the same draft-visibility authorization check used by `get_post()` before returning any redirect.
  - Only emit the redirect for published posts, or for draft posts when the authenticated user is the draft author.
  - Add a regression test proving that renamed draft paths still return `404` to unauthenticated and non-owner users.
- Mitigation:
  - If redirect compatibility is required immediately, restrict the fallback redirect to published posts only until draft-aware authorization is added.
- False positive notes:
  - This is not a direct content disclosure. The exposed data is existence plus canonical path/slug metadata. The issue remains real because the repository’s security model explicitly treats draft existence as non-public.

## Medium Severity

No medium-severity findings in the reviewed diff.

## Low Severity

No low-severity findings in the reviewed diff.
