# Live Search Dropdown PR Review

**Date:** 2026-03-17
**Scope:** `origin/main...HEAD` (13 commits, 11 files, ~1,579 lines added)
**Feature:** Live search dropdown in header, AbortSignal support for searchPosts, dark mode fix for label graph
**Review agents:** code-reviewer, pr-test-analyzer, silent-failure-hunter, comment-analyzer

---

## Critical Issues (2 found)

### 1. [error-hunter] Silent error swallowing — no user feedback on API failure

**`Header.tsx:70-74`**

The `.catch()` block logs to console and closes the dropdown, but gives the user zero feedback. This is the only error handler in the entire frontend that doesn't render an error message. Users can't distinguish a failed search from having no results — the dropdown just vanishes. This affects network failures, HTTP 401 (session expired), 429 (rate-limited), and 500s.

**Fix:** Add a `dropdownError` state. On non-abort errors, set an error message and keep the dropdown open so the user sees "Search failed. Please try again."

### 2. [test-analyzer] "ArrowDown + Enter" test doesn't verify navigation

**`Header.test.tsx:379`**

The test titled "arrow down highlights first result, enter navigates to it" only asserts `aria-selected` is true — it never presses Enter or checks the URL. The `LocationDisplay` helper is already available for this assertion.

---

## Important Issues (7 found)

### 3. [error-hunter] Stale results not cleared on error

**`Header.tsx:70-74`** — When an API call fails, `dropdownResults` is never cleared. Stale results from a previous query remain in state.

### 4. [test-analyzer] No regex metacharacter test for highlightMatch

**`highlightMatch.test.ts`** — The `escapeRegex` function is critical but untested. Queries like `C++`, `what?`, or `[draft]` would crash without it. CLAUDE.md also recommends property-based testing (fast-check) for pure functions like this.

### 5. [test-analyzer] Result click test doesn't assert navigation URL

**`Header.test.tsx:347`** — Checks the listbox disappears but doesn't verify the URL becomes `/post/posts/hello.md`.

### 6. [test-analyzer] Footer click test doesn't assert navigation URL

**`Header.test.tsx:473`** — Same gap — doesn't verify URL becomes `/search?q=hello`.

### 7. [comment-analyzer] highlightMatch JSDoc is temporally misleading

**`highlightMatch.ts:4`** — Says "HTML-escaped before processing" but the code actually splits first, then escapes each fragment. This could mislead a security reviewer.

### 8. [error-hunter] AbortError detection may miss ky-wrapped errors

**`Header.tsx:71`** — Checks for `DOMException` with `name === 'AbortError'`, but ky may re-wrap abort errors during its `afterResponse` hooks. Consider also checking `err instanceof Error && err.name === 'AbortError'`.

### 9. [error-hunter] No loading state for search

**`Header.tsx:28-32`** — No `isSearching` indicator. On slow connections, users can't tell if search is loading, has no results, or has failed.

---

## Suggestions (6 found)

### 10. [comment-analyzer] Strengthen the nosemgrep security comment

**`SearchDropdown.tsx:59`** — Comment is accurate but should note the output is only used as element innerHTML, not attribute content, which is what makes the limited escaping sufficient.

### 11. [test-analyzer] Add AbortError-specific silent handling test

**`Header.test.tsx`** — No test confirms that abort errors are silently swallowed without `console.error`.

### 12. [test-analyzer] Add onBlur behavior test

**`Header.tsx:189-196`** — The two `onBlur` branches (empty query -> close all, non-empty -> dismiss dropdown only) have no direct test.

### 13. [test-analyzer] Refactor raw setTimeout to fake timers

**`Header.test.tsx:342,498`** — Two tests use `setTimeout(r, 400)` instead of `vi.useFakeTimers()`. Brittle if debounce interval changes.

### 14. [test-analyzer] Switch raw dispatchEvent to fireEvent.mouseDown

**`SearchDropdown.test.tsx:57,65`** — Uses `dispatchEvent(new MouseEvent(...))` instead of `fireEvent.mouseDown()`, bypassing React's synthetic event system.

### 15. [comment-analyzer] Test comment/code mismatch

**`SearchDropdown.test.tsx:56`** — Comment says "Use fireEvent" but code actually uses `dispatchEvent`.

---

## Strengths

- **Race condition handling is excellent** — `clearTimeout` + `abort()` + `signal.aborted` guard is correct and well-tested (Header.test.tsx:503-534)
- **Security is solid** — `highlightMatch` HTML-escapes before inserting `<mark>` tags, with XSS test coverage
- **ARIA/accessibility is thorough** — combobox pattern with listbox, options, aria-selected, aria-expanded, aria-activedescendant
- **Double-ESC staged dismissal** is well-designed and tested
- **Stale highlight index** test catches a subtle UX bug (type -> arrow down -> edit -> Enter should submit the form, not navigate to stale result)
- **LabelGraphPage dark mode fix** correctly replaces hardcoded hex with semantic CSS variables
- **No CLAUDE.md violations** in naming, style, or architecture

---

## Recommended Action

1. **Fix critical issues** #1 (error feedback) and #2 (test assertion gap)
2. **Address important issues** #3-#6 (stale results, regex test, navigation assertions, JSDoc)
3. **Consider** #7-#9 and suggestions based on scope/timeline
4. Re-run targeted review after fixes
