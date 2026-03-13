# Comprehensive PR Review — 2026-03-13

Review of 5 commits against origin/main (42 files, +720/-182 lines).

## Commits Reviewed

- 81bf9bf fix: allow empty label names and unify label search
- d0a121e fix: align password minimum with 8-character policy
- bf492ae fix: sort social connect options alphabetically
- 9b95def fix: sort social accounts by platform
- 1f73f29 feat: refine sharing and cross-posting ui

## Critical Issues (0 found)

None.

## Important Issues (5 found — all fixed)

### 1. Raw `<a href>` instead of React Router `<Link>` — [code-reviewer]

**`frontend/src/components/crosspost/CrossPostSection.tsx:109-113`**

Used `<a href="/admin?tab=social">` which causes a full page reload. All other internal navigation uses `<Link>` from `react-router-dom`. Replaced with `<Link to="/admin?tab=social">`.

### 2-5. Bare `catch` blocks discard error context — [silent-failure-hunter]

Four locations used bare `catch` (no error binding), preventing differentiation between session expiry (401), validation errors, and network failures. Fixed to bind errors and differentiate 401 with "Session expired. Please log in again.":

- **`CrossPostSection.tsx`** — history and accounts fetch catch blocks
- **`CrossPostDialog.tsx`** — cross-post action catch block (also parses HTTP error details)
- **`EditorPage.tsx`** — social accounts fetch catch block
- **`SocialAccountsPanel.tsx`** — Facebook pages fetch catch block (uses `extractErrorDetail`)

## Suggestions (9 found)

### Test Coverage Gaps — [test-analyzer] — all fixed

1. **`searchUtils.test.ts`** — Added negative-match test and empty-names-array tests
2. **`ShareBar.test.tsx`** — Added "Publish this draft to enable sharing." assertion when disabled
3. **`EditorPage.test.tsx`** — Added test: save-as-draft with platforms selected should NOT open cross-post dialog
4. **`label_service.py`** — Unit test for `create_label(session, "test", names=None)` deferred (API layer always provides a list)

### Code Simplification — [code-simplifier] — deferred

5. **`CrossPostSection.tsx`** — Collapse duplicated error banner markup into array-driven rendering
6. **`SocialAccountsPanel.tsx`** — Convert `getPlatformDisplayName` if/else to Record lookup
7. **`SocialAccountsPanel.tsx`** — Use `localeCompare` with `{ sensitivity: 'base' }` instead of manual `toLocaleLowerCase()`
8. **`AdminPage.tsx`** — Derive tab validation from `ADMIN_TABS` constant
9. **`searchUtils.ts`** — Inline `normalizeLabelSearchQuery` (single-use wrapper)

## Strengths

- Elimination of explicit silent failures in `CrossPostSection.tsx`
- Excellent TDD discipline — boundary tests for password policy and empty label names
- Proper draft gating across share, cross-post, and editor flows
- Clean extraction of label search logic into shared `searchUtils.ts`
- Social account sorting is deterministic and well-tested
- Architecture docs kept in sync with changes
