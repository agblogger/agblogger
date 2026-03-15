# PR Review: All Changes vs origin/main

**Date**: 2026-03-15
**Scope**: 71 files, ~6.8k insertions, ~760 deletions across 55 commits
**Agents used**: code-reviewer, pr-test-analyzer, silent-failure-hunter, comment-analyzer, coderabbit

**Status**: All issues resolved. `just check` passes.

---

## Critical Issues (3 found — all resolved)

### 1. **[RESOLVED]** `UNION ALL` in recursive CTE risks infinite recursion

**File**: `backend/services/label_service.py:162`

Changed `UNION ALL` to `UNION` in `get_label_descendants_batch` to match `get_label_descendant_ids` and prevent infinite recursion on cyclic data. Added diamond-DAG deduplication test.

### 2. **[RESOLVED]** `include_descendants` default mismatch between service and API

**File**: `backend/services/post_service.py:83`

Changed default from `True` to `False` to match the API endpoint's opt-in contract. Added regression test verifying exact-match behavior when `include_descendants` is not specified.

### 3. **[NOT A BUG]** EditorPage missing `useUnsavedChanges` hook

**File**: `frontend/src/pages/EditorPage.tsx`

Investigation revealed `useEditorAutoSave` (already used by EditorPage) provides identical navigation guards: its own `useBlocker(isDirty)`, `beforeunload` listener, and `markSaved()` bypass. Adding `useUnsavedChanges` would create duplicate blockers (React Router warns: "A router only supports one blocker at a time"). Added two tests verifying the existing behavior.

---

## Important Issues (7 found — all resolved)

### 4. **[RESOLVED]** `siteStore.ts` empty catch block discards error context

Changed bare `catch {}` to `catch (err)` with `console.error('fetchConfig failed:', err)`. Added test verifying error logging.

### 5. **[RESOLVED]** `refreshSiteConfig()` errors are invisible to users

Updated to accept optional `onError` callback. Callers can now surface stale-config warnings. Added tests for callback invocation on failure.

### 6. **[RESOLVED]** PostPage doesn't use `AlertBanner` component

Replaced inline error divs for `publishError` and `deleteError` with `<AlertBanner variant="error">`. Added tests verifying correct CSS classes.

### 7. **[RESOLVED]** AdminPage dirty state not reset on confirmed tab switch

Added explicit `setSiteDirty(false)`, `setPagesDirty(false)`, `setAccountDirty(false)` after user confirms leaving dirty tab. Added test verifying no re-prompt on subsequent switches.

### 8. **[RESOLVED]** FilterPanel label fetch error only in console

Added `labelLoadError` state. Error message "Failed to load labels" now displays in the label list area. Added test with mocked fetch rejection.

### 9. **[RESOLVED]** `_download_file` doesn't catch transport errors

Added `except httpx.TransportError` handler alongside `HTTPStatusError`. Added tests for `ConnectError` handling and sync survival.

### 10. **[RESOLVED]** TimelinePage missing `includeSublabels` test coverage

Added two tests: one verifying `includeSublabels=true` is forwarded to `fetchPosts`, another verifying it's absent when not in the URL.

---

## Suggestions (8 found — all resolved)

| # | Issue | Resolution |
|---|-------|------------|
| 11 | `filterState` not memoized | Wrapped with `useMemo` keyed on `[searchParams, parsedLabelMode]` |
| 12 | `navigator.platform` deprecated | Replaced with `/Mac\|iPhone\|iPad\|iPod/.test(navigator.userAgent)` |
| 13 | Empty backup dirs accumulate | Added cleanup with `shutil.rmtree` + parent `rmdir` when `backed_up == 0` |
| 14 | Stale PR review findings | Marked #2, #8 as **[RESOLVED]**, #11 as **[INCORRECT]** |
| 15 | AGENTS.md typo | Fixed "unsanboxed" → "unsandboxed" |
| 16 | Spec diverged from implementation | Updated FileStrip/EditorPage consumer examples with implementation notes |
| 17 | Fragile timestamp assertion | Replaced `len == 17` with `re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}", ...)` |
| 18 | `linePrefix` precedence undocumented | Added JSDoc to `WrapAction.linePrefix` field |

---

## Strengths

- `useUnsavedChanges` hook has excellent JSDoc explaining the two-pronged guard strategy and `markSaved()` timing rationale
- `useFileUpload` hook properly uses refs for callback stability with test coverage for referential stability
- Batch descendant query using `json_each()` avoids N+1 queries
- Sync backup handles per-file errors defensively, including path traversal validation
- Property-based tests for `wrapSelection` with 500+ runs and meaningful invariant checks
- Error handling tests are thorough across page components (401, 404, 409, 422 variants)
- `AlertBanner`/`BackLink`/`ErrorBlock` extraction reduces duplication
- Architecture docs consolidation is cleaner and eliminates prior redundancy
- Backend sync client tests follow TDD with clearly labeled regression tests
- Integration tests cover the full API flow for `includeSublabels` with behavioral assertions
