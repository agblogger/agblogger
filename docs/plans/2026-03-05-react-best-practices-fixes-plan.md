# React Best Practices Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all issues identified in docs/reviews/2026-03-05-react-best-practices-review.md

**Architecture:** Pure frontend changes -- lazy-loading heavy libraries (XYFlow, KaTeX), fixing a memory leak in themeStore, adding React.memo to list-rendered components, hoisting constants/RegExp, and adding useMemo where needed.

**Tech Stack:** React 19, TypeScript, Zustand, Vitest, @testing-library/react

---

### Task 1: Hoist RegExp in shareUtils.ts

**Files:**
- Modify: `frontend/src/components/share/shareUtils.ts:98-103`
- Test: `frontend/src/components/share/__tests__/shareUtils.test.ts`

**Step 1: Verify existing tests pass**

Run: `cd frontend && npx vitest run src/components/share/__tests__/shareUtils.test.ts`
Expected: PASS

**Step 2: Hoist the regex to module level**

In `shareUtils.ts`, extract the inline regex to a module-level constant:

```typescript
const HOSTNAME_RE = /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$/
```

Then in `isValidHostname`:

```typescript
export function isValidHostname(value: string): boolean {
  let hostname = value.replace(/^https?:\/\//, '')
  hostname = hostname.trim()
  if (hostname === '') return false
  return HOSTNAME_RE.test(hostname)
}
```

**Step 3: Run tests to verify no regressions**

Run: `cd frontend && npx vitest run src/components/share/__tests__/shareUtils.test.ts`
Expected: PASS

**Step 4: Commit**

```
feat: hoist hostname regex to module level in shareUtils
```

---

### Task 2: Hoist tab definitions in AdminPage.tsx

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx:116-136`
- Test: `frontend/src/pages/__tests__/AdminPage.test.tsx`

**Step 1: Verify existing tests pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/AdminPage.test.tsx`
Expected: PASS

**Step 2: Extract tab definitions to module level**

Above the `AdminPage` function, add:

```typescript
const ADMIN_TABS = [
  { key: 'settings', label: 'Settings' },
  { key: 'pages', label: 'Pages' },
  { key: 'password', label: 'Password' },
  { key: 'social', label: 'Social' },
] as const
```

Then replace the inline array (lines 117-122) with `ADMIN_TABS.map(...)`.

**Step 3: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/AdminPage.test.tsx`
Expected: PASS

**Step 4: Commit**

```
refactor: hoist admin tab definitions to module level
```

---

### Task 3: Fix themeStore memory leak

**Files:**
- Modify: `frontend/src/stores/themeStore.ts:50-73`
- Test: `frontend/src/stores/__tests__/themeStore.test.ts`

**Step 1: Write a failing test for cleanup**

Add to themeStore.test.ts:

```typescript
it('returns a cleanup function from init that removes the MQL listener', () => {
  const removeSpy = vi.fn()
  vi.stubGlobal('matchMedia', (query: string) => ({
    ...makeMql(query),
    removeEventListener: removeSpy,
  }))

  const cleanup = useThemeStore.getState().init()
  expect(typeof cleanup).toBe('function')
  cleanup()
  expect(removeSpy).toHaveBeenCalledWith('change', expect.any(Function))
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/stores/__tests__/themeStore.test.ts`
Expected: FAIL -- init() currently returns void, not a cleanup function

**Step 3: Implement the fix**

In `themeStore.ts`, change the `init` method to return a cleanup function:

```typescript
init: () => {
  let stored: ThemeMode | null
  try {
    stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  } catch {
    stored = null
  }
  const mode: ThemeMode = stored === 'light' || stored === 'dark' || stored === 'system'
    ? stored
    : 'system'
  const resolved = resolveTheme(mode)
  applyTheme(resolved)
  set({ mode, resolvedTheme: resolved })

  const mql = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = () => {
    const current = get().mode
    if (current === 'system') {
      const newResolved = getSystemTheme()
      applyTheme(newResolved)
      set({ resolvedTheme: newResolved })
    }
  }
  mql.addEventListener('change', handler)
  return () => mql.removeEventListener('change', handler)
},
```

Update the `ThemeState` interface:

```typescript
init: () => () => void
```

Update `App.tsx` to use the cleanup:

```typescript
useEffect(() => {
  void fetchConfig()
  void checkAuth()
  const cleanupTheme = initTheme()
  return cleanupTheme
}, [fetchConfig, checkAuth, initTheme])
```

**Step 4: Run tests**

Run: `cd frontend && npx vitest run src/stores/__tests__/themeStore.test.ts`
Expected: PASS

**Step 5: Commit**

```
fix: return cleanup function from themeStore.init to prevent memory leak
```

---

### Task 4: Add useMemo to FilterPanel filteredLabels

**Files:**
- Modify: `frontend/src/components/filters/FilterPanel.tsx:1,63-67`
- Test: `frontend/src/components/filters/__tests__/FilterPanel.test.tsx`

**Step 1: Verify existing tests pass**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx`
Expected: PASS

**Step 2: Wrap filteredLabels in useMemo**

Add `useMemo` to the import, then replace:

```typescript
const filteredLabels = useMemo(
  () =>
    allLabels.filter(
      (l) =>
        l.id.toLowerCase().includes(labelSearch.toLowerCase()) ||
        l.names.some((n) => n.toLowerCase().includes(labelSearch.toLowerCase())),
    ),
  [allLabels, labelSearch],
)
```

**Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx`
Expected: PASS

**Step 4: Commit**

```
perf: memoize filtered labels computation in FilterPanel
```

---

### Task 5: Memoize PostCard component

**Files:**
- Modify: `frontend/src/components/posts/PostCard.tsx`
- Test: `frontend/src/components/posts/__tests__/PostCard.test.tsx`

**Step 1: Write a test that verifies memo behavior**

Add to PostCard.test.tsx:

```typescript
it('is memoized with React.memo', () => {
  const post = makePost()
  const { rerender } = renderCard(post)
  // Re-render with same props -- if memoized, component should not re-execute
  // We verify by checking PostCard has a displayName set by memo
  expect(PostCard).toHaveProperty('$$typeof')
  // Also verify it renders correctly after rerender
  rerender(
    <MemoryRouter>
      <PostCard post={post} />
    </MemoryRouter>,
  )
  expect(screen.getByText('Test Post')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/posts/__tests__/PostCard.test.tsx`
Expected: FAIL -- PostCard is a plain function, not wrapped in memo

**Step 3: Wrap PostCard in React.memo**

```typescript
import { memo } from 'react'

// ... keep the function as-is, but change the export:

function PostCardInner({ post, index = 0 }: PostCardProps) {
  // ... existing body
}

const PostCard = memo(PostCardInner)
export default PostCard
```

**Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/posts/__tests__/PostCard.test.tsx`
Expected: PASS

**Step 5: Commit**

```
perf: wrap PostCard in React.memo to prevent unnecessary re-renders
```

---

### Task 6: Memoize LabelChip component

**Files:**
- Modify: `frontend/src/components/labels/LabelChip.tsx`
- Test: `frontend/src/components/labels/__tests__/LabelChip.test.tsx`

**Step 1: Write test verifying memo**

Add to LabelChip.test.tsx:

```typescript
it('is wrapped in React.memo', () => {
  expect(LabelChip).toHaveProperty('$$typeof')
  // Verify the memo wrapper type
  expect((LabelChip as { $$typeof: symbol }).$$typeof.toString()).toContain('react.memo')
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelChip.test.tsx`
Expected: FAIL

**Step 3: Wrap LabelChip in React.memo**

```typescript
import { memo } from 'react'
import { Link } from 'react-router-dom'

// ... keep inner function, change export
function LabelChipInner({ labelId, clickable = true }: LabelChipProps) {
  // ... existing body
}

const LabelChip = memo(LabelChipInner)
export default LabelChip
```

**Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelChip.test.tsx`
Expected: PASS

**Step 5: Commit**

```
perf: wrap LabelChip in React.memo
```

---

### Task 7: Memoize SearchResultItem and wrap in React.memo

**Files:**
- Modify: `frontend/src/pages/SearchPage.tsx:123-144`
- Test: `frontend/src/pages/__tests__/SearchPage.test.tsx`

**Step 1: Verify existing tests pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/SearchPage.test.tsx`
Expected: PASS

**Step 2: Wrap SearchResultItem in React.memo**

```typescript
const SearchResultItem = memo(function SearchResultItem({
  result,
  index,
}: {
  result: SearchResult
  index: number
}) {
  // ... existing body
})
```

Add `memo` to the React import at top of file.

**Step 3: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/SearchPage.test.tsx`
Expected: PASS

**Step 4: Commit**

```
perf: wrap SearchResultItem in React.memo
```

---

### Task 8: Memoize interactiveFlowProps in LabelGraphPage

**Files:**
- Modify: `frontend/src/pages/LabelGraphPage.tsx:257-271`
- Test: `frontend/src/pages/__tests__/LabelGraphPage.test.tsx`

**Step 1: Verify existing tests pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelGraphPage.test.tsx`
Expected: PASS

**Step 2: Wrap interactiveFlowProps in useMemo**

Replace the direct object literal (lines 257-271) with:

```typescript
const interactiveFlowProps = useMemo<
  Pick<ReactFlowProps, 'isValidConnection' | 'onConnect' | 'onEdgeClick' | 'edgesReconnectable'>
>(
  () =>
    user
      ? {
          isValidConnection,
          onConnect: (connection) => {
            void onConnect(connection)
          },
          onEdgeClick: (event, edge) => {
            void onEdgeClick(event, edge)
          },
          edgesReconnectable: true,
        }
      : { edgesReconnectable: false },
  [user, isValidConnection, onConnect, onEdgeClick],
)
```

**Step 3: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelGraphPage.test.tsx`
Expected: PASS

**Step 4: Commit**

```
perf: memoize interactiveFlowProps in LabelGraphPage
```

---

### Task 9: Lazy-load LabelGraphPage

**Files:**
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Test: `frontend/src/pages/__tests__/LabelsPage.test.tsx`

**Step 1: Read LabelsPage.tsx to understand current usage**

Check how LabelGraphPage is imported and rendered within LabelsPage.

**Step 2: Write a test that lazy import works**

Add to LabelsPage.test.tsx:

```typescript
it('renders graph view with suspense fallback', async () => {
  // Switch to graph view and verify it eventually renders
  const user = userEvent.setup()
  await renderLabelsPage()
  const graphTab = screen.getByText('Graph')
  await user.click(graphTab)
  // Should show loading spinner or graph content
  await waitFor(() => {
    expect(screen.queryByText('Label Graph')).toBeInTheDocument()
  })
})
```

**Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelsPage.test.tsx`
Expected: FAIL or PASS -- depends on existing coverage

**Step 4: Convert to lazy import in LabelsPage.tsx**

Replace the static import:
```typescript
// Before:
import LabelGraphPage from '@/pages/LabelGraphPage'

// After:
import { lazy, Suspense } from 'react'
const LabelGraphPage = lazy(() => import('@/pages/LabelGraphPage'))
```

Wrap the graph view render in Suspense:
```tsx
<Suspense fallback={<LoadingSpinner />}>
  <LabelGraphPage viewToggle={viewToggle} />
</Suspense>
```

**Step 5: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelsPage.test.tsx`
Expected: PASS

**Step 6: Commit**

```
perf: lazy-load LabelGraphPage to reduce initial bundle size
```

---

### Task 10: Lazy-load KaTeX in useKatex hook

**Files:**
- Modify: `frontend/src/hooks/useKatex.ts`
- Test: `frontend/src/hooks/__tests__/useKatex.test.ts`

**Step 1: Read existing useKatex test**

Check the current test patterns for useKatex.

**Step 2: Write failing test for lazy behavior**

Add a test that verifies KaTeX is only loaded when math content is present:

```typescript
it('returns raw HTML unchanged when no math spans present', () => {
  const { result } = renderHook(() => useRenderedHtml('<p>Hello</p>'))
  expect(result.current).toBe('<p>Hello</p>')
})
```

**Step 3: Convert to lazy KaTeX import**

Since `useRenderedHtml` uses `useMemo`, we need a synchronous approach. The best strategy is to keep the static import but use `React.lazy` at the route level so pages using KaTeX-heavy content are code-split. The `useKatex.ts` hook is already well-optimized (regex-gated, memoized).

A more practical approach: the KaTeX CSS import is the real cost. Move it to a dynamic import:

```typescript
import { useMemo, useRef } from 'react'

let katexModule: typeof import('katex') | null = null
let cssLoaded = false

function ensureKatexCss() {
  if (!cssLoaded) {
    cssLoaded = true
    void import('katex/dist/katex.min.css')
  }
}

async function getKatex() {
  if (katexModule === null) {
    katexModule = await import('katex')
  }
  return katexModule.default
}

// ... keep MATH_SPAN_RE, HTML_ENTITY_RE, decodeHtmlEntities ...

export function useRenderedHtml(html: string | null | undefined): string {
  const katexRef = useRef<typeof import('katex').default | null>(null)
  const [, setLoaded] = useState(0)

  useMemo(() => {
    if (html != null && MATH_SPAN_RE.test(html) && katexRef.current === null) {
      ensureKatexCss()
      void getKatex().then((k) => {
        katexRef.current = k
        setLoaded((n) => n + 1)
      })
    }
  }, [html])

  return useMemo(() => {
    if (html == null) return ''
    if (katexRef.current === null) return html
    const katex = katexRef.current
    return html.replace(MATH_SPAN_RE, (_match, mode: string, tex: string) => {
      const displayMode = mode === 'display'
      const rendered = katex.renderToString(decodeHtmlEntities(tex.trim()), {
        throwOnError: false,
        displayMode,
      })
      return `<span class="math ${mode}">${rendered}</span>`
    })
  }, [html, katexRef.current])
}
```

**Note:** This is the most complex change. If the lazy approach creates test complexity, an alternative is to keep the static import but ensure KaTeX is code-split at the route level by lazy-loading pages that use it (PostPage, SearchPage, EditorPage). Evaluate both approaches and pick the simpler one.

**Step 4: Run tests**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useKatex.test.ts`
Expected: PASS

**Step 5: Run full test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS

**Step 6: Commit**

```
perf: lazy-load KaTeX to reduce initial bundle size
```

---

### Task 11: Run full check suite

**Step 1: Run static checks + tests**

Run: `just check`
Expected: PASS

**Step 2: Fix any issues**

Address lint, type, or test failures.

**Step 3: Final commit if needed**

```
fix: address static analysis issues from react best practices changes
```
