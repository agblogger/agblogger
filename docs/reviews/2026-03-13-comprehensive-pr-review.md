# Comprehensive PR Review — 2026-03-13

Review of 7 commits against origin/main (43 files, +989/-196 lines).

## Commits Reviewed

- 971a383 refactor: simplify crosspost, admin, and label search code
- 823b0ad fix: differentiate 401 errors in catch blocks and use client-side navigation
- 81bf9bf fix: allow empty label names and unify label search
- d0a121e fix: align password minimum with 8-character policy
- bf492ae fix: sort social connect options alphabetically
- 9b95def fix: sort social accounts by platform
- 1f73f29 feat: refine sharing and cross-posting ui

## Critical Issues (0 found)

None.

## Important Issues (4 found — all fixed)

### 1. `parseErrorDetail` may surface raw backend text on 5xx errors — [silent-failure-hunter]

`CrossPostDialog.tsx` and `SocialAccountsPanel.tsx` called `parseErrorDetail` for all non-401 HTTP errors including 5xx. If the backend includes internal details (stack traces, SQL, paths) in the `detail` field of a 500 response, those would be shown directly to the user.

**Fix:** Added `status >= 500` guard in both `CrossPostDialog.handlePost` and `SocialAccountsPanel.extractErrorDetail` to return the generic fallback for server errors, only parsing detail for 4xx client errors.

### 2. `EditorPage` post-load catch block missing 401 differentiation — [silent-failure-hunter]

The post-load catch block differentiated 404 but showed "Failed to load post" for 401 errors, inconsistent with the PR's other catch blocks that show "Session expired. Please log in again."

**Fix:** Added `err.response.status === 401` branch in `EditorPage.tsx` post-load catch block.

### 3. Duplicate React keys in `CrossPostSection` error banners — [code-reviewer]

`CrossPostSection.tsx` used `key={msg}` when rendering error banners from `[historyError, accountsError]`. When both API calls fail with the same error (e.g., both return 401 → "Session expired"), React sees duplicate keys.

**Fix:** Deduplicated error messages with `Set` before rendering, so identical messages appear once and keys are always unique.

### 4. Test description mismatch in `CrossPostHistory.test.tsx` — [comment-analyzer]

Test description said "Not shared yet." but assertion checked "No cross-posts yet."

**Fix:** Updated test description to match the actual assertion.

## Suggestions (from review agents — all addressed)

- ~~`parseErrorDetail` catch block returns fallback silently without logging~~ — Added `console.warn` in catch block
- 401 error banners show "Please log in again" but provide no link/redirect to login — Deferred (larger UX decision)
- ~~Duplicated `names_must_be_nonempty_strings` validator across `LabelCreate` and `LabelUpdate`~~ — Extracted shared `_validate_nonempty_names` helper
- ~~`VALID_TAB_KEYS` typed as `Set<string>` requires unsafe cast to `AdminTabKey`~~ — Changed to `Set<AdminTabKey>`, used `AdminTabKey` for `activeTab` state
- ~~`extractErrorDetail` is module-private but same 401 pattern repeated in 3 other components~~ — Extracted to `parseError.ts`, used by `SocialAccountsPanel`, `CrossPostDialog`, `CrossPostSection`, `EditorPage`
- ~~`ShareButton` defines own props instead of importing `ShareProps`~~ — Now imports `ShareProps` from `shareTypes.ts`
- ~~Missing tests for invalid `?tab=bogus` fallback and tab URL sync via useEffect~~ — Added both tests
- ~~Review document commit count and line numbers were outdated~~ — Fixed
- ~~`create_label` docstring doesn't mention `names=None` defaults to empty list~~ — Updated docstring

## Strengths

- Strong TDD discipline — every behavioral change has corresponding tests
- Excellent error differentiation in `CrossPostDialog.handlePost` (three-branch: 401 / other HTTP / non-HTTP)
- Clean extraction of label search logic into shared `searchUtils.ts`
- Proper draft gating across share, cross-post, and editor flows
- Architecture docs kept in sync with changes
- Smart sort-order regression tests (account names deliberately differ from platform names)
- No `type: ignore`, `noqa`, `eslint-disable`, or `fmt: skip` introduced
