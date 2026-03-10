# React Best Practices Review (Vercel Guidelines)

**Date:** 2026-03-10
**Scope:** Frontend codebase (`frontend/src/`)
**Framework:** Vercel React Best Practices (58 rules, 8 categories)

---

## 1. Eliminating Waterfalls (CRITICAL)

**`async-parallel` - Good: App initialization is parallel**
`App.tsx:33-38` — `fetchConfig()`, `checkAuth()`, and `initTheme()` all fire in parallel in the Layout effect. No waterfall.

**`async-parallel` - Good: EditorPage independent fetches**
`EditorPage.tsx:87-125` — Post data fetch and social accounts fetch run in separate effects but are independent. Both fire on mount effectively in parallel.

**`async-parallel` - Acceptable: PostPage publish sequence**
`PostPage.tsx:53-80` — `handlePublish()` calls `fetchPostForEdit()` then `updatePost()` sequentially. The first fetch is needed to get current data — necessary sequence.

**Verdict: Mostly clean.** No significant waterfalls detected.

---

## 2. Bundle Size Optimization (CRITICAL)

**`bundle-barrel-imports` - Clean.** No barrel files (`index.ts` re-exports) exist. All imports are direct path imports.

**`bundle-dynamic-imports` - Good: LabelGraphPage is lazy-loaded**
`LabelsPage.tsx` uses `lazy(() => import('@/pages/LabelGraphPage'))` with Suspense.

**`bundle-dynamic-imports` - Issue: All page routes are eagerly imported**
`App.tsx:3-13` — All 10 page components are statically imported. `EditorPage`, `AdminPage`, and `SearchPage` are auth-gated and used less frequently — good candidates for `React.lazy()`.

**`bundle-defer-third-party` - Good: KaTeX is lazy-loaded**
`useKatex.ts` dynamically imports KaTeX (~200KB) only when math content is detected.

**Verdict: Good lazy-loading for KaTeX and label graph. Route-level code splitting for less-used pages would further improve initial load.**

---

## 3. Server-Side Performance (HIGH)

Not applicable — this is a client-side SPA with no SSR/RSC.

---

## 4. Client-Side Data Fetching (MEDIUM-HIGH)

**`client-swr-dedup` - Issue: No request deduplication**
All API calls use raw `ky` with no caching or deduplication layer. If the same post is fetched from multiple components or rapid navigations, duplicate requests fire.

**`client-event-listeners` - Clean**
Event listeners properly scoped and cleaned up throughout.

**`client-passive-event-listeners` - Clean**
IntersectionObserver used instead of scroll listeners in `useActiveHeading`.

**`client-localstorage-schema` - Mostly clean**
Well-structured draft storage with `savedAt` timestamps and try-catch for private browsing, but **no schema versioning** for draft format.

**Verdict: Missing request deduplication is the biggest gap. For a blog with few concurrent views it's not urgent, but would improve UX for rapid navigation.**

---

## 5. Re-render Optimization (MEDIUM)

**`rerender-memo` - Good: List items are memoized**
`PostCard`, `LabelChip`, `SearchResultItem` — all wrapped in `memo()`.

**`rerender-memo` - Issue: `PlatformIcon` is not memoized**
`PlatformIcon.tsx` renders in lists (social accounts, editor checkboxes) but is not wrapped in `memo()`.

**`rerender-derived-state-no-effect` - Issue: Effect used for derived state**
`SocialAccountsPanel.tsx:60-62` — An effect syncs `localBusy` to parent via `onBusyChange`. Classic "effect to sync derived state" anti-pattern.

**`rerender-move-effect-to-event` - Issue: EditorPage author effect**
`EditorPage.tsx:111-115` — An effect syncs author state from user data. This could be derived during render instead.

**`rerender-functional-setstate` - Good**
Functional setState used correctly throughout.

**`rerender-lazy-state-init` - Clean**
`useKatex.ts` uses lazy state initialization.

**Verdict: Good memoization on list items. A few effects could be replaced with derived state.**

---

## 6. Rendering Performance (MEDIUM)

**`rendering-conditional-render` - Clean**
Most conditional renders use ternary. `&&` patterns are safe (always produce JSX, never falsy primitives).

**Verdict: No significant rendering performance issues.**

---

## 7. JavaScript Performance (LOW-MEDIUM)

**`js-set-map-lookups` - Minor: Array.includes for platform selection**
`EditorPage.tsx:425` — `selectedPlatforms.includes(acct.platform)` inside `.map()`. With ~4 platforms this is fine.

**`js-early-exit` - Good**
Functions return early on guard conditions throughout.

**Verdict: No actionable JS performance issues.**

---

## 8. Advanced Patterns (LOW)

**`advanced-event-handler-refs` - Used correctly**
`SocialAccountsPanel.tsx:57-58` — `onBusyChangeRef` pattern keeps callback stable.

**Verdict: Clean.**

---

## Summary of Actionable Findings

| Priority | Issue | Location | Effort |
|----------|-------|----------|--------|
| Priority | Issue | Location | Status |
|----------|-------|----------|--------|
| CRITICAL | Route-level code splitting for `EditorPage`, `AdminPage`, `SearchPage` | `App.tsx` | **FIXED** — lazy-loaded with Suspense |
| MEDIUM | `PlatformIcon` not memoized (rendered in lists) | `PlatformIcon.tsx` | **FIXED** — wrapped in `memo()` |
| MEDIUM | Effect-based derived state sync for busy state | `SocialAccountsPanel.tsx:60-62` | **Not a real issue** — ref+effect pattern is correct for notifying parent of derived state; explicit test validates callback stability |
| MEDIUM | Editor author could be derived during render | `EditorPage.tsx` | **FIXED** — replaced effect with render-time derivation |
| LOW | Draft localStorage has no schema version | `useEditorAutoSave.ts` | **FIXED** — added `_v` schema version; stale drafts are silently discarded |

## What's Already Done Well

- No barrel files — direct imports throughout
- KaTeX and LabelGraphPage are lazy-loaded
- List components (`PostCard`, `LabelChip`) are properly memoized
- Parallel app initialization (no startup waterfalls)
- IntersectionObserver used instead of scroll listeners
- Functional `setState` used correctly
- Event listener cleanup is thorough
- Zustand selectors prevent unnecessary re-renders
- CSRF token caching prevents redundant fetches
- localStorage access wrapped in try-catch for private browsing
