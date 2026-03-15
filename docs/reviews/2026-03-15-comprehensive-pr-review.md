# Comprehensive PR Review — 2026-03-15

Review of 48 commits (origin/main..HEAD) spanning 57 files, ~5400 lines added, ~550 removed.

**Features reviewed:** opt-in sublabel filtering, unsaved changes detection, editor image/blockquote toolbar buttons, clickable label chips on PostCard, label hierarchy display, labels page search, sync conflict backup.

**Review agents:** code-reviewer, pr-test-analyzer, silent-failure-hunter, comment-analyzer.

---

## Critical Issues (3)

### 1. `_backup_conflicted_files` crashes sync on filesystem errors

**File:** `cli/sync_client.py:307-334`
**Category:** error-handling

`shutil.copy2` and `mkdir` have no try-except. A permission error or full disk aborts the entire sync with an unhandled traceback. Backup is a best-effort safety net — it should degrade gracefully.

**Fix:** Wrap `shutil.copy2` in `try/except OSError`, print a warning, continue. Also guard the `_backup_conflicted_files()` call in `sync()`.

### 2. `useFileUpload` silently swallows errors when `onError` omitted

**File:** `frontend/src/components/editor/useFileUpload.ts:42-48`
**Category:** error-handling

`onError` is optional. When not provided, upload failures are completely silent — no console log, no user feedback. Both current callers pass `onError`, but the hook's contract allows silent failures. Additionally, non-`HTTPError` exceptions (TypeError, SyntaxError) are masked as generic "Failed to upload files" with no console logging.

**Fix:** Add `console.error` fallback when `onError` is not provided, and always `console.error` non-HTTP errors.

### 3. Missing test: `include_descendants=False` with `label_mode="and"`

**File:** `tests/test_api/test_api_integration.py`
**Category:** test-coverage

The new `list_posts` code path for AND mode + exact match has no integration test. Only OR mode is tested with/without sublabels.

**Fix:** Add a test: post with labels [a, b], query `labels=a,b&labelMode=and&includeSublabels=false` → found; query `labels=a,c&labelMode=and&includeSublabels=false` → not found.

---

## Important Issues (5)

### 4. Missing test: `markSaved` happy path in `useUnsavedChanges`

**File:** `frontend/src/hooks/__tests__/useUnsavedChanges.test.ts`
**Category:** test-coverage

The core contract of `markSaved` (calling it allows next navigation without confirm prompt) is never tested. Only the reset-after-re-dirty scenario is covered.

### 5. Missing test: `onStart` callback in `useFileUpload`

**File:** `frontend/src/components/editor/__tests__/useFileUpload.test.ts`
**Category:** test-coverage

`onStart` clears errors in FileStrip but is never verified in tests. If it stops being called, stale errors persist alongside successful uploads.

### 6. Spec vs implementation mismatch: image button tooltip

**File:** `docs/specs/2026-03-15-editor-image-blockquote-buttons-design.md:142`
**Category:** comment-accuracy

Spec says two distinct disabled tooltips ("Save post first" vs "Only directory-backed posts support images"). Implementation has only one tooltip used for both states, which is misleading for saved flat-file posts.

### 7. Spec vs implementation mismatch: FileStrip consumer example

**File:** `docs/specs/2026-03-15-editor-image-blockquote-buttons-design.md:103`
**Category:** comment-accuracy

Spec shows `onSuccess: loadAssets` but actual implementation is `onSuccess: () => void loadAssets()` plus `onStart: () => setError(null)` which the spec omits.

### 8. No notification when backup skips non-existent files

**File:** `cli/sync_client.py:325-326`
**Category:** error-handling

Non-existent files are silently skipped with `continue`, no message printed. User thinks all conflicts were backed up but some were skipped. Inconsistent with the path-traversal skip which does print.

---

## Suggestions (4)

### 9. `useUnsavedChanges` hook lacks documentation

**File:** `frontend/src/hooks/useUnsavedChanges.ts`

The `markSaved` ref-bypass pattern is non-obvious. The spec at `docs/specs/2026-03-15-unsaved-changes-detection-design.md:26` has an excellent explanation of the React re-render timing gap that belongs in the code itself.

### 10. `handleInsertAtCursor` silently fails if textarea ref is null

**File:** `frontend/src/pages/EditorPage.tsx:214-215`

Image uploads succeed server-side but markdown insertion silently fails if ref is null. Consider appending to body as fallback.

### 11. Spec contradicts implementation on add-page dirty tracking

**File:** `docs/specs/2026-03-15-unsaved-changes-detection-design.md:114`

Non-goals say add-page form is excluded from dirty tracking, but `PagesSection.tsx:126` includes `addPageDirty` in the dirty computation.

### 12. `datetime.now()` without explicit timezone

**File:** `cli/sync_client.py:316`

Works fine for local backup naming, but `datetime.now(tz=UTC)` would be more explicit.

---

## Strengths

- **Strong test coverage overall** — all major features have dedicated tests, including property-based tests for `wrapSelection`
- **Security practices** — path traversal protection in backup, `dangerouslySetInnerHTML` justification preserved, no internal error details exposed to clients
- **CLAUDE.md compliance** — modern Python typing, correct TypeScript naming conventions, no suppression comments
- **Well-structured backend** — `include_descendants` parameter handles all four code paths (descendants+AND/OR, exact+AND/OR) cleanly
- **Sync backup integration tests** — cover path traversal rejection, nonexistent files, multi-file scenarios
- **LabelSettingsPage error handling** — exemplary status-code-specific messages (409, 404, 401)
- **Cross-referencing comment in `useActiveHeading`** — correctly updated 112px/7rem → 128px/8rem across all three connected values (rootMargin, scroll-margin-top, sticky offset)
