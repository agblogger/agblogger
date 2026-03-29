# Security Best Practices Review — 2026-03-29

**Scope**: Security review of the current branch against `origin/main`, focused on the new FastAPI SEO/server-preload flow and the React preload consumers.

## Executive Summary

No critical or high-severity issues were identified in the reviewed diff.

One medium-severity issue was found: the new preload bootstrap trusts a globally-addressable DOM ID that untrusted rendered content can also claim. On post pages, that creates a stored admin action-confusion path until the SWR revalidation request replaces the forged preload state.

## Findings

### Medium

1. **[SBP-001] Untrusted rendered content can clobber `__initial_data__` and feed forged preload JSON into admin post actions**

   - **Location**:
     - `backend/pandoc/renderer.py:87`
     - `backend/services/seo_service.py:95-101`
     - `frontend/src/utils/preload.ts:16-23`
     - `frontend/src/hooks/usePost.ts:15-20`
     - `frontend/src/pages/PostPage.tsx:53-59`
     - `frontend/src/pages/PostPage.tsx:72-85`
   - **Evidence**:
     - The sanitizer still allows global `id` attributes on rendered markdown HTML (`backend/pandoc/renderer.py:87`).
     - The server injects the real preload payload as `<script id="__initial_data__" type="application/json">...` (`backend/services/seo_service.py:95-101`).
     - The frontend reads preload data with `document.getElementById('__initial_data__')` and removes whatever matching element it finds first (`frontend/src/utils/preload.ts:16-23`).
     - `PostPage` uses the preloaded `post.file_path` immediately for destructive or privileged actions such as delete and publish (`frontend/src/pages/PostPage.tsx:53-59`, `frontend/src/pages/PostPage.tsx:72-85`).
   - **Impact**:
     - A malicious post or page body can contain markup such as `<div id="__initial_data__">{...}</div>`. Because user-authored HTML is rendered before the real preload script, the SPA can consume attacker-controlled JSON on first paint.
     - On `PostPage`, an authenticated admin can then see and act on forged post metadata until SWR finishes revalidation. In practice, that means delete/publish/edit/cross-post flows can temporarily target attacker-chosen `file_path` values under the admin session.
   - **Fix**:
     - Make the preload marker unforgeable by rendered content. The cleanest option is to add a dedicated attribute that the sanitizer does not allow, for example `data-agblogger-preload`, and select it with `document.body.querySelector('script[data-agblogger-preload][type="application/json"]')`.
     - Keep the preload script outside `#root` and avoid selectors based only on shared IDs.
     - Add a regression test that renders markdown containing `id="__initial_data__"` and proves the frontend still consumes only the server-owned preload script.
   - **False-positive notes**:
     - This finding depends on user-authored HTML retaining `id` attributes after sanitization. The current renderer explicitly allows them.

## Conclusion

Beyond the issue above, I did not find additional security regressions in the reviewed diff that rose above low-severity or speculative risk.
