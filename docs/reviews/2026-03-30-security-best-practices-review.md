# Security Best Practices Review — 2026-03-30

**Scope**: Security review of the current branch against `origin/main`, focused on the FastAPI backend changes (quota enforcement, SEO/server-rendered routes, auth/admin updates, sync) and the React preload/admin consumers.

## Executive Summary

No critical or high-severity issues were identified in the reviewed diff.

One medium-severity issue was found: the new `MAX_CONTENT_SIZE` control can be bypassed because multiple write paths only account for part of the bytes they add under `content_dir`. That weakens the branch's new disk-exhaustion guardrail for compromised admin sessions or abused automation credentials.

## Findings

### Medium

1. **[SBP-001] `MAX_CONTENT_SIZE` undercounts real `content_dir` growth, so the new quota can be exceeded**

   - **Impact**: A compromised admin session or sync credential can still grow on-disk state beyond the configured storage cap, weakening the new availability control intended to prevent disk exhaustion.
   - **Location**:
     - `backend/services/storage_quota.py:3-4`
     - `backend/services/storage_quota.py:40-63`
     - `backend/api/admin.py:137-152`
     - `backend/api/admin.py:201-231`
     - `backend/api/admin.py:256-279`
     - `backend/services/admin_service.py:167-176`
     - `backend/api/posts.py:338-349`
     - `backend/api/posts.py:367-431`
     - `backend/api/posts.py:854-857`
     - `backend/api/posts.py:893-895`
     - `backend/services/git_service.py:21-23`
     - `backend/services/git_service.py:42-57`
     - `backend/services/git_service.py:67-75`
   - **Evidence**:
     - The tracker is explicitly defined as tracking total byte usage under the whole `content_dir`, not just markdown payload files (`backend/services/storage_quota.py:3-4`, `backend/services/storage_quota.py:40-63`).
     - Page creation checks only the initial page body size and then adjusts by the new `*.md` file size (`backend/api/admin.py:137-152`), but the same request also rewrites `index.toml` to append the page entry (`backend/services/admin_service.py:172-176`). Those extra bytes are never counted.
     - Page updates and deletes similarly adjust only the page file delta (`backend/api/admin.py:201-231`, `backend/api/admin.py:256-279`) even though title/order/config changes mutate `index.toml`.
     - Markdown uploads validate against the raw multipart byte count (`backend/api/posts.py:367-368`) but the server later normalizes and serializes the post before writing it (`backend/api/posts.py:338-349`, `backend/api/posts.py:390-413`). The tracked delta is still the raw upload size (`backend/api/posts.py:430-431`), so server-added front matter is not included.
     - Post create/update paths also track only the working-tree markdown delta (`backend/api/posts.py:854-857`, `backend/api/posts.py:893-895`), while every successful mutation also creates new Git objects inside the same `content_dir` because the repository lives there and commits run there (`backend/services/git_service.py:21-23`, `backend/services/git_service.py:42-57`, `backend/services/git_service.py:67-75`).
   - **Abuse path**:
     - Fill the quota close to its limit.
     - Repeatedly create tiny pages or posts, or upload markdown that omits metadata so the server expands it during serialization.
     - Each request stays under the tracked delta while `index.toml` growth, normalized front matter, and Git object growth continue increasing actual disk usage under `content_dir`.
   - **Fix**:
     - Enforce quota against the final on-disk delta for the entire mutation, not only selected payload files.
     - For page mutations, include the pre/post size delta of `index.toml` (and any other config files touched).
     - For uploaded markdown, compute the serialized markdown byte size before the quota check and use that value instead of the raw upload size.
     - Recompute the tracker after successful Git commits, or explicitly account for Git metadata if `MAX_CONTENT_SIZE` is intended to cover the whole `content_dir`.
     - Add regression tests that prove near-limit page creation, page title edits, and repeated committed post writes cannot push actual `content_dir` usage past the configured cap.

## Conclusion

Beyond the quota-accounting gap above, I did not find additional security regressions in the reviewed diff that rose above low-severity or speculative risk.
