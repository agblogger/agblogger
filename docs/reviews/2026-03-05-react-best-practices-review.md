# React Best Practices Review (Vercel Guidelines)

**Date:** 2026-03-05
**Scope:** Full frontend review against Vercel React Best Practices (58 rules, 8 categories)

---

## CRITICAL Priority

### 1. Heavy libraries not lazy-loaded (`bundle-dynamic-imports`)

| Library | File | Impact |
|---------|------|--------|
| `@xyflow/react` + `@dagrejs/dagre` (~200KB) | `pages/LabelGraphPage.tsx:1-22` | Loaded on every page; only used on label graph view |
| `katex` (~200KB) | `hooks/useKatex.ts:2-3` | Loaded at module level; only needed if post contains math |

**Fix:** Use `React.lazy()` + `<Suspense>` for LabelGraphPage; conditionally import KaTeX only when math content is detected.

## HIGH Priority

### 2. Memory leak -- event listener never removed

- **`stores/themeStore.ts:65`** -- `mql.addEventListener('change', ...)` in `init()` has no cleanup. The MediaQueryList listener persists indefinitely.

### 3. Missing `useMemo` on filtered label list

- **`components/filters/FilterPanel.tsx:63-67`** -- `filteredLabels` is recalculated every render with `.filter()` + `.includes()` + `.toLowerCase()` on potentially large arrays. Should be wrapped in `useMemo`.

## MEDIUM Priority

### 4. Expensive components not memoized (`rerender-memo`)

| Component | File | Reason |
|-----------|------|--------|
| `PostCard` | `components/posts/PostCard.tsx` | Rendered in lists (TimelinePage), calls `useRenderedHtml` (KaTeX) |
| `LabelChip` | `components/labels/LabelChip.tsx` | Rendered many times across pages |
| `SearchResultItem` | `pages/SearchPage.tsx:123-144` | Each item runs KaTeX rendering per render |

### 5. Non-primitive objects created during render (`rerender-memo-with-default-value`)

- **`pages/LabelGraphPage.tsx:257-271`** -- `interactiveFlowProps` object literal created every render. Hoist or `useMemo`.

### 6. `Array.includes()` in hot paths instead of `Set` (`js-set-map-lookups`)

| File | Line | Pattern |
|------|------|---------|
| `components/filters/FilterPanel.tsx` | 70 | `value.labels.includes(id)` in map render |
| `components/editor/LabelInput.tsx` | 46, 51, 58 | `value.includes(l.id)` in filter |

### 7. Static JSX/constants not hoisted (`rendering-hoist-jsx`)

- **`pages/AdminPage.tsx:117`** -- Tab definitions array recreated every render; should be a module-level constant.

### 8. RegExp not hoisted (`js-hoist-regexp`)

- **`components/share/shareUtils.ts:102`** -- Hostname validation regex created on every call. Hoist to module level.

## LOW Priority

### 9. localStorage draft data not versioned (`client-localstorage-schema`)

- **`hooks/useEditorAutoSave.ts:41-58`** -- Draft format has no version field; format changes will silently break old drafts.

### 10. Conditional rendering uses `&&` throughout

Most instances are safe (checking `.length > 0`, booleans, or null), but using ternaries would be more defensive and consistent.

---

## Already Well-Done

- `Promise.all()` used correctly in AdminPage, LabelPostsPage, LabelSettingsPage
- `Set` used properly in CrossPostDialog for platform selection
- Static constants hoisted in MarkdownToolbar (`buttons`), shareUtils (`SHARE_PLATFORMS`), CrossPostDialog (`CHAR_LIMITS`)
- Event listeners properly cleaned up in Header, TableOfContents, LabelInput, useEditorAutoSave
- Functional `setState` used correctly (e.g., `setRetryCount((c) => c + 1)`)
- RegExp hoisted correctly in `useKatex.ts` (`MATH_SPAN_RE`, `HTML_ENTITY_RE`)
