# SWR Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual useEffect+useState data-fetching patterns with SWR across the frontend, and fix two AnalyticsPanel review findings.

**Architecture:** Install SWR, add a global `SWRConfig` provider, create typed hooks per resource, migrate 16 components from manual fetch patterns to SWR hooks. Existing API functions in `frontend/src/api/` are reused as SWR fetchers. Tests use `SWRConfig` with `provider: () => new Map()` for cache isolation.

**Tech Stack:** SWR, React, ky, Vitest, @testing-library/react

**Spec:** `docs/specs/2026-03-25-swr-migration-design.md`

---

## File Structure

### New files

- `frontend/src/hooks/useSWRFetch.ts` — typed wrapper around `useSWR` using the global fetcher
- `frontend/src/hooks/useLabels.ts` — shared hook for label list
- `frontend/src/hooks/useSocialAccounts.ts` — shared hook for social accounts
- `frontend/src/hooks/usePost.ts` — post detail + view count
- `frontend/src/hooks/useAdminData.ts` — admin site settings + pages (two hooks, one file)
- `frontend/src/hooks/useLabelGraph.ts` — label graph data
- `frontend/src/hooks/useLabelPosts.ts` — label + posts for a label ID
- `frontend/src/hooks/usePage.ts` — single page by ID
- `frontend/src/hooks/usePostAssets.ts` — post file assets
- `frontend/src/hooks/useCrossPostHistory.ts` — cross-post history for a post
- `frontend/src/hooks/useAnalyticsDashboard.ts` — composite analytics dashboard + referrers
- `frontend/src/test/swrWrapper.tsx` — shared test utility for SWR cache isolation
- `frontend/src/hooks/__tests__/useLabels.test.ts` — hook tests
- `frontend/src/hooks/__tests__/useSocialAccounts.test.ts`
- `frontend/src/hooks/__tests__/usePost.test.ts`
- `frontend/src/hooks/__tests__/useAdminData.test.ts`
- `frontend/src/hooks/__tests__/useLabelGraph.test.ts`
- `frontend/src/hooks/__tests__/useLabelPosts.test.ts`
- `frontend/src/hooks/__tests__/usePage.test.ts`
- `frontend/src/hooks/__tests__/usePostAssets.test.ts`
- `frontend/src/hooks/__tests__/useCrossPostHistory.test.ts`
- `frontend/src/hooks/__tests__/useAnalyticsDashboard.test.ts`

### Modified files

- `frontend/package.json` — add `swr` dependency
- `frontend/src/App.tsx` — wrap with `SWRConfig`
- `frontend/src/components/admin/AnalyticsPanel.tsx` — review fixes + SWR migration
- `frontend/src/pages/PostPage.tsx` — SWR migration
- `frontend/src/pages/AdminPage.tsx` — SWR migration
- `frontend/src/pages/LabelsPage.tsx` — SWR migration (LabelListView)
- `frontend/src/pages/LabelGraphPage.tsx` — SWR migration
- `frontend/src/pages/LabelPostsPage.tsx` — SWR migration
- `frontend/src/pages/PageViewPage.tsx` — SWR migration
- `frontend/src/pages/LabelCreatePage.tsx` — SWR migration
- `frontend/src/pages/LabelSettingsPage.tsx` — SWR migration
- `frontend/src/pages/EditorPage.tsx` — SWR migration (social accounts only)
- `frontend/src/components/filters/FilterPanel.tsx` — SWR migration
- `frontend/src/components/editor/LabelInput.tsx` — SWR migration
- `frontend/src/components/crosspost/CrossPostSection.tsx` — SWR migration
- `frontend/src/components/crosspost/SocialAccountsPanel.tsx` — SWR migration
- `frontend/src/components/editor/FileStrip.tsx` — SWR migration
- All corresponding `__tests__/` files for the above components

---

## Task 1: AnalyticsPanel review fixes (no SWR)

**Files:**
- Modify: `frontend/src/components/admin/AnalyticsPanel.tsx`
- Modify: `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx`

These are standalone fixes independent of SWR.

- [ ] **Step 1: Add test for sort memoization**

In `AnalyticsPanel.test.tsx`, add a test that verifies the top pages table renders paths sorted by views descending (this validates the existing behavior that must be preserved after the refactor):

```tsx
it('renders top pages sorted by views descending', async () => {
  setupDefaultMocks()
  render(<AnalyticsPanel busy={false} onBusyChange={vi.fn()} />)
  await waitFor(() => {
    expect(screen.getByText('/posts/hello')).toBeInTheDocument()
  })
  const rows = screen.getAllByRole('button', { name: /View referrers for/ })
  expect(rows[0]).toHaveAttribute('aria-label', 'View referrers for /posts/hello')
  expect(rows[1]).toHaveAttribute('aria-label', 'View referrers for /posts/world')
})
```

- [ ] **Step 2: Run test to verify it passes** (validates existing behavior)

Run: `cd frontend && npx vitest run src/components/admin/__tests__/AnalyticsPanel.test.tsx --reporter=verbose`

- [ ] **Step 3: Extract sorted paths into useMemo**

In `AnalyticsPanel.tsx`, add `useMemo` import and replace the inline sort + topPage computation:

```tsx
import { useEffect, useMemo, useRef, useState } from 'react'

// Inside the component, after the state declarations:
const sortedPaths = useMemo(
  () => [...paths].sort((a, b) => b.views - a.views),
  [paths],
)
const topPage = sortedPaths.length > 0 && sortedPaths[0] ? sortedPaths[0].path : '—'
```

Remove the `topPage` state variable and `setTopPage` calls. Remove the `if (pathsData.paths.length > 0)` block in `loadDashboard` that computes topPage.

In the JSX, replace `{[...paths].sort((a, b) => b.views - a.views).map((p) => (` with `{sortedPaths.map((p) => (`.

- [ ] **Step 4: Fix initial load effect**

Replace the `initialLoadRef` + no-deps effect:

```tsx
// Remove these lines:
const initialLoadRef = useRef(false)
useEffect(() => {
  if (!initialLoadRef.current) {
    initialLoadRef.current = true
    void loadDashboard(dateRange)
  }
})

// Replace with:
useEffect(() => {
  void loadDashboard('7d')
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [])
```

Note: Since Task 14 will replace this code entirely with SWR hooks, this intermediate fix keeps it simple. Wrap `loadDashboard` in `useCallback` to avoid needing an eslint-disable comment:

```tsx
const loadDashboardCb = useCallback(loadDashboard, [])

useEffect(() => {
  void loadDashboardCb('7d')
}, [loadDashboardCb])
```

- [ ] **Step 5: Run tests to verify both fixes**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/AnalyticsPanel.test.tsx --reporter=verbose`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/admin/AnalyticsPanel.tsx frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx
git commit -m "fix: memoize sorted paths and fix initial load effect in AnalyticsPanel"
```

---

## Task 2: Install SWR and add infrastructure

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/hooks/useSWRFetch.ts`
- Create: `frontend/src/test/swrWrapper.tsx`

- [ ] **Step 1: Install SWR**

```bash
cd frontend && npm install swr
```

- [ ] **Step 2: Create test utility for SWR cache isolation**

Create `frontend/src/test/swrWrapper.tsx`:

```tsx
import { SWRConfig } from 'swr'
import type { ReactNode } from 'react'

export function SWRTestWrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  )
}
```

`dedupingInterval: 0` ensures tests don't get stale cached results between test cases.

- [ ] **Step 3: Create useSWRFetch helper**

Create `frontend/src/hooks/useSWRFetch.ts`:

```tsx
import useSWR from 'swr'
import type { SWRConfiguration } from 'swr'

/**
 * Typed wrapper around useSWR that uses the global fetcher from SWRConfig.
 * Keys are ky-relative URL paths (e.g., 'labels', 'posts/my-slug').
 * Pass null as key to suppress fetching.
 */
export function useSWRFetch<T>(key: string | null, options?: SWRConfiguration<T>) {
  return useSWR<T>(key, options)
}
```

- [ ] **Step 4: Add SWRConfig provider to App.tsx**

In `frontend/src/App.tsx`, add imports and wrap the `Layout` component's return JSX (inside the `Layout` function, around the existing content):

```tsx
import { SWRConfig } from 'swr'
import api from '@/api/client'
```

Wrap the router's `Layout` element return. The `SWRConfig` must be inside the router (so hooks can access route context) but wrapping the main content. Add it inside the `Layout` component's return, wrapping `<div className="min-h-screen bg-paper">`:

```tsx
return (
  <SWRConfig value={{ fetcher: (url: string) => api.get(url).json(), dedupingInterval: 2000 }}>
    <div className="min-h-screen bg-paper">
      {/* existing Header, main, footer */}
    </div>
  </SWRConfig>
)
```

- [ ] **Step 5: Run full frontend checks**

```bash
cd frontend && npx vitest run --reporter=verbose
```

Ensure no regressions from adding SWRConfig.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/App.tsx frontend/src/hooks/useSWRFetch.ts frontend/src/test/swrWrapper.tsx
git commit -m "feat: install SWR and add global config provider"
```

---

## Task 3: useLabels hook (shared, 5 consumers)

**Files:**
- Create: `frontend/src/hooks/useLabels.ts`
- Create: `frontend/src/hooks/__tests__/useLabels.test.ts`

- [ ] **Step 1: Write hook tests**

Create `frontend/src/hooks/__tests__/useLabels.test.ts`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockFetchLabels = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
}))

import { useLabels } from '../useLabels'

const LABELS = [
  { id: 'tech', names: ['tech'], is_implicit: false, parents: [], children: [], post_count: 5 },
  { id: 'blog', names: ['blog'], is_implicit: false, parents: [], children: [], post_count: 3 },
]

describe('useLabels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns labels on success', async () => {
    mockFetchLabels.mockResolvedValue(LABELS)
    const { result } = renderHook(() => useLabels(), { wrapper: SWRTestWrapper })

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(LABELS)
    expect(result.current.error).toBeUndefined()
  })

  it('returns error on failure', async () => {
    mockFetchLabels.mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useLabels(), { wrapper: SWRTestWrapper })

    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.data).toBeUndefined()
  })

  it('deduplicates concurrent calls', async () => {
    mockFetchLabels.mockResolvedValue(LABELS)

    // Both hooks must share the same SWR cache to test deduplication.
    // Render a single component that calls useLabels() twice.
    function DualConsumer() {
      const r1 = useLabels()
      const r2 = useLabels()
      return <div data-r1={JSON.stringify(r1.data)} data-r2={JSON.stringify(r2.data)} />
    }
    render(<SWRTestWrapper><DualConsumer /></SWRTestWrapper>)

    await waitFor(() => {
      expect(mockFetchLabels).toHaveBeenCalled()
    })
    // SWR deduplicates: only one fetch call
    expect(mockFetchLabels).toHaveBeenCalledTimes(1)
  })
})
```

Note: The dedup test needs both hooks to share the same SWR cache. Render them with the same wrapper instance or use a shared wrapper component.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useLabels.test.ts --reporter=verbose`
Expected: FAIL — module `../useLabels` not found

- [ ] **Step 3: Implement useLabels hook**

Create `frontend/src/hooks/useLabels.ts`:

```tsx
import useSWR from 'swr'
import { fetchLabels } from '@/api/labels'
import type { LabelResponse } from '@/api/client'

export function useLabels() {
  return useSWR<LabelResponse[]>('labels', fetchLabels)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useLabels.test.ts --reporter=verbose`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useLabels.ts frontend/src/hooks/__tests__/useLabels.test.ts
git commit -m "feat: add useLabels SWR hook with deduplication"
```

---

## Task 4: useSocialAccounts hook (shared, 3 consumers)

**Files:**
- Create: `frontend/src/hooks/useSocialAccounts.ts`
- Create: `frontend/src/hooks/__tests__/useSocialAccounts.test.ts`

- [ ] **Step 1: Write hook tests**

Create `frontend/src/hooks/__tests__/useSocialAccounts.test.ts`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockFetchSocialAccounts = vi.fn()

vi.mock('@/api/crosspost', () => ({
  fetchSocialAccounts: (...args: unknown[]) => mockFetchSocialAccounts(...args) as unknown,
}))

import { useSocialAccounts } from '../useSocialAccounts'

const ACCOUNTS = [
  { id: 1, platform: 'bluesky', account_name: '@test.bsky.social', created_at: '2026-01-01' },
]

describe('useSocialAccounts', () => {
  beforeEach(() => vi.clearAllMocks())

  it('returns accounts on success', async () => {
    mockFetchSocialAccounts.mockResolvedValue(ACCOUNTS)
    const { result } = renderHook(() => useSocialAccounts(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(ACCOUNTS)
  })

  it('returns error on failure', async () => {
    mockFetchSocialAccounts.mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useSocialAccounts(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSocialAccounts.test.ts --reporter=verbose`

- [ ] **Step 3: Implement hook**

Create `frontend/src/hooks/useSocialAccounts.ts`:

```tsx
import useSWR from 'swr'
import { fetchSocialAccounts } from '@/api/crosspost'
import type { SocialAccount } from '@/api/crosspost'

export function useSocialAccounts() {
  return useSWR<SocialAccount[]>('crosspost/accounts', fetchSocialAccounts)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSocialAccounts.test.ts --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSocialAccounts.ts frontend/src/hooks/__tests__/useSocialAccounts.test.ts
git commit -m "feat: add useSocialAccounts SWR hook"
```

---

## Task 5: usePost and useViewCount hooks

**Files:**
- Create: `frontend/src/hooks/usePost.ts`
- Create: `frontend/src/hooks/__tests__/usePost.test.ts`

- [ ] **Step 1: Write hook tests**

Create `frontend/src/hooks/__tests__/usePost.test.ts`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockFetchPost = vi.fn()
const mockFetchViewCount = vi.fn()

vi.mock('@/api/posts', () => ({
  fetchPost: (...args: unknown[]) => mockFetchPost(...args) as unknown,
}))

vi.mock('@/api/analytics', () => ({
  fetchViewCount: (...args: unknown[]) => mockFetchViewCount(...args) as unknown,
}))

import { usePost, useViewCount } from '../usePost'

const POST = {
  id: 1, file_path: 'posts/hello', title: 'Hello', author: null,
  created_at: '2026-01-01', modified_at: '2026-01-01', is_draft: false,
  rendered_excerpt: null, labels: [], rendered_html: '<p>hi</p>', content: null,
}

describe('usePost', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches post by slug', async () => {
    mockFetchPost.mockResolvedValue(POST)
    const { result } = renderHook(() => usePost('posts/hello'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(POST)
    expect(mockFetchPost).toHaveBeenCalledWith('posts/hello')
  })

  it('does not fetch when slug is null', async () => {
    const { result } = renderHook(() => usePost(null), { wrapper: SWRTestWrapper })
    // Should stay in non-loading state with no data
    expect(result.current.data).toBeUndefined()
    expect(mockFetchPost).not.toHaveBeenCalled()
  })
})

describe('useViewCount', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches view count by slug', async () => {
    mockFetchViewCount.mockResolvedValue({ views: 42 })
    const { result } = renderHook(() => useViewCount('posts/hello'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual({ views: 42 })
  })

  it('does not fetch when slug is null', async () => {
    const { result } = renderHook(() => useViewCount(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
    expect(mockFetchViewCount).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/usePost.test.ts --reporter=verbose`

- [ ] **Step 3: Implement hooks**

Create `frontend/src/hooks/usePost.ts`:

```tsx
import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'

export function usePost(slug: string | null) {
  return useSWR<PostDetail>(
    slug !== null ? ['post', slug] : null,
    ([, s]: [string, string]) => fetchPost(s),
  )
}

export function useViewCount(slug: string | null) {
  return useSWR<ViewCountResponse>(
    slug !== null ? ['viewCount', slug] : null,
    ([, s]: [string, string]) => fetchViewCount(s),
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/usePost.test.ts --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/usePost.ts frontend/src/hooks/__tests__/usePost.test.ts
git commit -m "feat: add usePost and useViewCount SWR hooks"
```

---

## Task 6: Remaining single-use hooks (useAdminData, useLabelGraph, useLabelPosts, usePage, usePostAssets, useCrossPostHistory)

**Files:**
- Create: `frontend/src/hooks/useAdminData.ts`
- Create: `frontend/src/hooks/useLabelGraph.ts`
- Create: `frontend/src/hooks/useLabelPosts.ts`
- Create: `frontend/src/hooks/usePage.ts`
- Create: `frontend/src/hooks/usePostAssets.ts`
- Create: `frontend/src/hooks/useCrossPostHistory.ts`
- Create: corresponding `__tests__/` files for each

These hooks all follow the same pattern. Each test file tests: success, error, and null-key suppression (where applicable).

- [ ] **Step 1: Write test files for all 6 hooks**

Each test follows the same structure as Tasks 3-5: mock the API module, use `SWRTestWrapper`, test success/error/null-key. Example for each:

**useAdminData.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
const mockFetchAdminSiteSettings = vi.fn()
const mockFetchAdminPages = vi.fn()
vi.mock('@/api/admin', () => ({
  fetchAdminSiteSettings: (...args: unknown[]) => mockFetchAdminSiteSettings(...args) as unknown,
  fetchAdminPages: (...args: unknown[]) => mockFetchAdminPages(...args) as unknown,
}))
import { useAdminSiteSettings, useAdminPages } from '../useAdminData'

describe('useAdminSiteSettings', () => {
  beforeEach(() => vi.clearAllMocks())
  it('returns settings on success', async () => {
    const settings = { title: 'Blog', description: 'My blog', timezone: 'UTC' }
    mockFetchAdminSiteSettings.mockResolvedValue(settings)
    const { result } = renderHook(() => useAdminSiteSettings(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(settings)
  })
  it('returns error on failure', async () => {
    mockFetchAdminSiteSettings.mockRejectedValue(new Error('fail'))
    const { result } = renderHook(() => useAdminSiteSettings(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
  })
})

describe('useAdminPages', () => {
  beforeEach(() => vi.clearAllMocks())
  it('returns pages on success', async () => {
    const pages = { pages: [{ id: 'about', title: 'About', file: null, is_builtin: true, content: null }] }
    mockFetchAdminPages.mockResolvedValue(pages)
    const { result } = renderHook(() => useAdminPages(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(pages)
  })
})
```

**useLabelGraph.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
const mockFetchLabelGraph = vi.fn()
vi.mock('@/api/labels', () => ({
  fetchLabelGraph: (...args: unknown[]) => mockFetchLabelGraph(...args) as unknown,
}))
import { useLabelGraph } from '../useLabelGraph'

describe('useLabelGraph', () => {
  beforeEach(() => vi.clearAllMocks())
  it('returns graph on success', async () => {
    const graph = { nodes: [{ id: 'tech', names: ['tech'], post_count: 5 }], edges: [] }
    mockFetchLabelGraph.mockResolvedValue(graph)
    const { result } = renderHook(() => useLabelGraph(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(graph)
  })
  it('returns error on failure', async () => {
    mockFetchLabelGraph.mockRejectedValue(new Error('fail'))
    const { result } = renderHook(() => useLabelGraph(), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
  })
})
```

**useLabelPosts.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
const mockFetchLabel = vi.fn()
const mockFetchLabelPosts = vi.fn()
vi.mock('@/api/labels', () => ({
  fetchLabel: (...args: unknown[]) => mockFetchLabel(...args) as unknown,
  fetchLabelPosts: (...args: unknown[]) => mockFetchLabelPosts(...args) as unknown,
}))
import { useLabelPosts } from '../useLabelPosts'

describe('useLabelPosts', () => {
  beforeEach(() => vi.clearAllMocks())
  it('fetches label and posts in parallel', async () => {
    const label = { id: 'tech', names: ['tech'], is_implicit: false, parents: [], children: [], post_count: 5 }
    const posts = { posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 }
    mockFetchLabel.mockResolvedValue(label)
    mockFetchLabelPosts.mockResolvedValue(posts)
    const { result } = renderHook(() => useLabelPosts('tech'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data?.label).toEqual(label)
    expect(result.current.data?.posts).toEqual(posts)
  })
  it('does not fetch when labelId is null', () => {
    const { result } = renderHook(() => useLabelPosts(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
    expect(mockFetchLabel).not.toHaveBeenCalled()
  })
})
```

**usePage.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
// usePage uses the global fetcher, so mock the api client
vi.mock('@/api/client', () => ({
  default: { get: vi.fn() },
}))
import api from '@/api/client'
import { usePage } from '../usePage'

describe('usePage', () => {
  beforeEach(() => vi.clearAllMocks())
  it('fetches page by ID', async () => {
    const page = { id: 'about', title: 'About', rendered_html: '<p>About</p>' }
    ;(api.get as ReturnType<typeof vi.fn>).mockReturnValue({ json: () => Promise.resolve(page) })
    const { result } = renderHook(() => usePage('about'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(page)
  })
  it('does not fetch when pageId is null', () => {
    const { result } = renderHook(() => usePage(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
  })
})
```

**usePostAssets.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
const mockFetchPostAssets = vi.fn()
vi.mock('@/api/posts', () => ({
  fetchPostAssets: (...args: unknown[]) => mockFetchPostAssets(...args) as unknown,
}))
import { usePostAssets } from '../usePostAssets'

describe('usePostAssets', () => {
  beforeEach(() => vi.clearAllMocks())
  it('fetches assets by filePath', async () => {
    const assets = { assets: [{ name: 'img.png', size: 1024, is_image: true }] }
    mockFetchPostAssets.mockResolvedValue(assets)
    const { result } = renderHook(() => usePostAssets('posts/hello'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(assets)
  })
  it('does not fetch when filePath is null', () => {
    const { result } = renderHook(() => usePostAssets(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
    expect(mockFetchPostAssets).not.toHaveBeenCalled()
  })
  it('refetches when refreshToken changes', async () => {
    mockFetchPostAssets.mockResolvedValue({ assets: [] })
    const { result, rerender } = renderHook(
      ({ fp, token }) => usePostAssets(fp, token),
      { wrapper: SWRTestWrapper, initialProps: { fp: 'posts/hello' as string | null, token: 0 } },
    )
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(mockFetchPostAssets).toHaveBeenCalledTimes(1)
    rerender({ fp: 'posts/hello', token: 1 })
    await waitFor(() => expect(mockFetchPostAssets).toHaveBeenCalledTimes(2))
  })
})
```

**useCrossPostHistory.test.ts:**
```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
const mockFetchCrossPostHistory = vi.fn()
vi.mock('@/api/crosspost', () => ({
  fetchCrossPostHistory: (...args: unknown[]) => mockFetchCrossPostHistory(...args) as unknown,
}))
import { useCrossPostHistory } from '../useCrossPostHistory'

describe('useCrossPostHistory', () => {
  beforeEach(() => vi.clearAllMocks())
  it('fetches history by filePath', async () => {
    const history = { items: [{ platform: 'bluesky', url: 'https://bsky.app/...' }] }
    mockFetchCrossPostHistory.mockResolvedValue(history)
    const { result } = renderHook(() => useCrossPostHistory('posts/hello'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data).toEqual(history)
  })
  it('does not fetch when filePath is null', () => {
    const { result } = renderHook(() => useCrossPostHistory(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
    expect(mockFetchCrossPostHistory).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they all fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useAdminData.test.ts src/hooks/__tests__/useLabelGraph.test.ts src/hooks/__tests__/useLabelPosts.test.ts src/hooks/__tests__/usePage.test.ts src/hooks/__tests__/usePostAssets.test.ts src/hooks/__tests__/useCrossPostHistory.test.ts --reporter=verbose`

- [ ] **Step 3: Implement all 6 hooks**

**useAdminData.ts:**
```tsx
import useSWR from 'swr'
import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import type { AdminSiteSettings, AdminPagesResponse } from '@/api/client'

export function useAdminSiteSettings() {
  return useSWR<AdminSiteSettings>('admin/site', fetchAdminSiteSettings)
}

export function useAdminPages() {
  return useSWR<AdminPagesResponse>('admin/pages', fetchAdminPages)
}
```

**useLabelGraph.ts:**
```tsx
import useSWR from 'swr'
import { fetchLabelGraph } from '@/api/labels'
import type { LabelGraphResponse } from '@/api/client'

export function useLabelGraph() {
  return useSWR<LabelGraphResponse>('labels/graph', fetchLabelGraph)
}
```

**useLabelPosts.ts:**
```tsx
import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

export function useLabelPosts(labelId: string | null) {
  return useSWR<LabelPostsData>(
    labelId !== null ? ['labelPosts', labelId] : null,
    async ([, id]: [string, string]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
  )
}
```

**usePage.ts:**
```tsx
import useSWR from 'swr'
import type { PageResponse } from '@/api/client'

/** Uses the global fetcher from SWRConfig. Key: `pages/${pageId}` */
export function usePage(pageId: string | null) {
  return useSWR<PageResponse>(pageId !== null ? `pages/${pageId}` : null)
}
```

**usePostAssets.ts:**
```tsx
import useSWR from 'swr'
import { fetchPostAssets } from '@/api/posts'
import type { AssetListResponse } from '@/api/client'

/**
 * The refreshToken parameter is optional. When the parent component uploads new assets,
 * it increments refreshToken. This is included in the SWR key so a new token triggers
 * a refetch. After delete/rename mutations, call mutate() instead.
 */
export function usePostAssets(filePath: string | null, refreshToken = 0) {
  return useSWR<AssetListResponse>(
    filePath !== null ? ['postAssets', filePath, refreshToken] : null,
    ([, fp]: [string, string, number]) => fetchPostAssets(fp),
  )
}
```

**useCrossPostHistory.ts:**
```tsx
import useSWR from 'swr'
import { fetchCrossPostHistory } from '@/api/crosspost'
import type { CrossPostHistory } from '@/api/crosspost'

export function useCrossPostHistory(filePath: string | null) {
  return useSWR<CrossPostHistory>(
    filePath !== null ? ['crossPostHistory', filePath] : null,
    ([, fp]: [string, string]) => fetchCrossPostHistory(fp),
  )
}
```

- [ ] **Step 4: Run tests to verify they all pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useAdminData.test.ts src/hooks/__tests__/useLabelGraph.test.ts src/hooks/__tests__/useLabelPosts.test.ts src/hooks/__tests__/usePage.test.ts src/hooks/__tests__/usePostAssets.test.ts src/hooks/__tests__/useCrossPostHistory.test.ts --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAdminData.ts frontend/src/hooks/useLabelGraph.ts frontend/src/hooks/useLabelPosts.ts frontend/src/hooks/usePage.ts frontend/src/hooks/usePostAssets.ts frontend/src/hooks/useCrossPostHistory.ts frontend/src/hooks/__tests__/
git commit -m "feat: add remaining single-use SWR hooks"
```

---

## Task 7: useAnalyticsDashboard and usePathReferrers hooks

**Files:**
- Create: `frontend/src/hooks/useAnalyticsDashboard.ts`
- Create: `frontend/src/hooks/__tests__/useAnalyticsDashboard.test.ts`

- [ ] **Step 1: Write hook tests**

Create `frontend/src/hooks/__tests__/useAnalyticsDashboard.test.ts`. Test:
- `useAnalyticsDashboard('7d')` calls all 5 API functions in parallel, returns composite data
- `usePathReferrers(pathId)` fetches referrers, null pathId suppresses fetch

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockFetchAnalyticsSettings = vi.fn()
const mockFetchTotalStats = vi.fn()
const mockFetchPathHits = vi.fn()
const mockFetchBreakdown = vi.fn()
const mockFetchPathReferrers = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) => mockFetchAnalyticsSettings(...args) as unknown,
  fetchTotalStats: (...args: unknown[]) => mockFetchTotalStats(...args) as unknown,
  fetchPathHits: (...args: unknown[]) => mockFetchPathHits(...args) as unknown,
  fetchBreakdown: (...args: unknown[]) => mockFetchBreakdown(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
}))

import { useAnalyticsDashboard, usePathReferrers } from '../useAnalyticsDashboard'

describe('useAnalyticsDashboard', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches all 5 resources in parallel', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue({ analytics_enabled: true, show_views_on_posts: false })
    mockFetchTotalStats.mockResolvedValue({ total_views: 100, total_unique: 50 })
    mockFetchPathHits.mockResolvedValue({ paths: [] })
    mockFetchBreakdown.mockResolvedValue({ category: 'browsers', entries: [] })

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.data?.settings.analytics_enabled).toBe(true)
    expect(result.current.data?.stats.total_views).toBe(100)
    expect(mockFetchAnalyticsSettings).toHaveBeenCalledTimes(1)
    expect(mockFetchTotalStats).toHaveBeenCalledTimes(1)
    expect(mockFetchPathHits).toHaveBeenCalledTimes(1)
    expect(mockFetchBreakdown).toHaveBeenCalledTimes(2) // browsers + systems
  })
})

describe('usePathReferrers', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches referrers for a path ID', async () => {
    mockFetchPathReferrers.mockResolvedValue({ path_id: 1, referrers: [{ referrer: 'google.com', count: 10 }] })
    const { result } = renderHook(() => usePathReferrers(1), { wrapper: SWRTestWrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.data?.referrers).toHaveLength(1)
  })

  it('does not fetch when pathId is null', () => {
    const { result } = renderHook(() => usePathReferrers(null), { wrapper: SWRTestWrapper })
    expect(result.current.data).toBeUndefined()
    expect(mockFetchPathReferrers).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useAnalyticsDashboard.test.ts --reporter=verbose`

- [ ] **Step 3: Implement hooks**

Create `frontend/src/hooks/useAnalyticsDashboard.ts`:

```tsx
import useSWR from 'swr'
import {
  fetchAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchBreakdown,
  fetchPathReferrers,
} from '@/api/analytics'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  BreakdownEntry,
  PathReferrersResponse,
} from '@/api/client'

export interface AnalyticsDashboardData {
  settings: AnalyticsSettings
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownEntry[]
  operatingSystems: BreakdownEntry[]
}

type DateRange = '7d' | '30d' | '90d'

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  start.setDate(start.getDate() - days)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  }
}

export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)
  return useSWR<AnalyticsDashboardData>(
    ['analytics-dashboard', start, end],
    async () => {
      const [settings, stats, paths, browsersData, osData] = await Promise.all([
        fetchAnalyticsSettings(),
        fetchTotalStats(start, end),
        fetchPathHits(start, end),
        fetchBreakdown('browsers', start, end),
        fetchBreakdown('systems', start, end),
      ])
      return {
        settings,
        stats,
        paths,
        browsers: browsersData.entries,
        operatingSystems: osData.entries,
      }
    },
  )
}

export function usePathReferrers(pathId: number | null) {
  return useSWR<PathReferrersResponse>(
    pathId !== null ? ['pathReferrers', pathId] : null,
    ([, id]: [string, number]) => fetchPathReferrers(id),
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useAnalyticsDashboard.test.ts --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAnalyticsDashboard.ts frontend/src/hooks/__tests__/useAnalyticsDashboard.test.ts
git commit -m "feat: add useAnalyticsDashboard and usePathReferrers SWR hooks"
```

---

## Task 8: Migrate PostPage to SWR hooks

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`
- Modify: `frontend/src/pages/__tests__/PostPage.test.tsx`

- [ ] **Step 1: Update PostPage tests**

The existing tests mock `@/api/posts` and `@/api/analytics` directly. After migration, PostPage will use `usePost` and `useViewCount` hooks. Update the test mocks:

- Add `vi.mock('@/hooks/usePost')` that provides mock `usePost` and `useViewCount` functions
- Remove the direct `fetchPost`/`fetchViewCount` mocks for the loading tests (mutation tests like delete/publish still use `@/api/posts` directly)
- Wrap renders in `SWRTestWrapper`

Preserve all existing test assertions — the user-facing behavior must not change.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate PostPage to use hooks**

In `PostPage.tsx`:
- Replace `fetchPost` and `fetchViewCount` imports with `usePost` and `useViewCount` from `@/hooks/usePost`
- Remove the `post` state, `loading` state, `loadError` state, `viewCount` state
- Remove the data-fetching `useEffect`
- Add:
  ```tsx
  const { data: post, error: postError, isLoading: loading } = usePost(slug ?? null)
  const { data: viewData } = useViewCount(slug ?? null)
  const viewCount = viewData?.views ?? null
  ```
- Derive `loadError` from `postError`:
  ```tsx
  const loadError = postError
    ? postError instanceof HTTPError && postError.response.status === 404
      ? 'Post not found'
      : postError instanceof HTTPError && postError.response.status === 401
        ? 'Session expired. Please log in again.'
        : 'Failed to load post. Please try again later.'
    : null
  ```
- Keep all mutation logic (delete, publish, edit) unchanged — those stay as direct API calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "refactor: migrate PostPage to usePost and useViewCount SWR hooks"
```

---

## Task 9: Migrate AdminPage to SWR hooks

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/pages/__tests__/AdminPage.test.tsx`

- [ ] **Step 1: Update AdminPage tests**

Update mocks to use `useAdminSiteSettings` and `useAdminPages` hooks. Wrap renders in `SWRTestWrapper`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/AdminPage.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate AdminPage**

Replace the `useEffect` that fetches `fetchAdminSiteSettings` + `fetchAdminPages` with:
```tsx
const { data: siteSettings, error: siteError, isLoading: siteLoading } = useAdminSiteSettings()
const { data: pagesData, error: pagesError, isLoading: pagesLoading } = useAdminPages()
const loading = siteLoading || pagesLoading
const loadError = (siteError ?? pagesError)
  ? (siteError ?? pagesError) instanceof HTTPError && (siteError ?? pagesError)?.response.status === 401
    ? 'Session expired. Please log in again.'
    : 'Failed to load admin data. Please try again later.'
  : null
```

Remove the loading/error/data state variables and the fetch `useEffect`. Pass `siteSettings` and `pagesData?.pages` to child components.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/AdminPage.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx frontend/src/pages/__tests__/AdminPage.test.tsx
git commit -m "refactor: migrate AdminPage to SWR hooks"
```

---

## Task 10: Migrate label consumers (FilterPanel, LabelsPage, LabelInput, LabelCreatePage, LabelSettingsPage)

**Files:**
- Modify: `frontend/src/components/filters/FilterPanel.tsx`
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Modify: `frontend/src/components/editor/LabelInput.tsx`
- Modify: `frontend/src/pages/LabelCreatePage.tsx`
- Modify: `frontend/src/pages/LabelSettingsPage.tsx`
- Modify: corresponding test files

All 5 components replace `fetchLabels()` + useState + useEffect with `useLabels()`.

- [ ] **Step 1: Update test mocks for all 5 components**

Each test file needs:
- Mock `@/hooks/useLabels` instead of (or in addition to) `@/api/labels`
- Wrap renders in `SWRTestWrapper` where the hook is used directly

Note: `LabelSettingsPage` also fetches `fetchLabel(labelId)`. Only the `fetchLabels()` call is replaced; the `fetchLabel` call becomes part of the initial load or can stay manual. Check the existing pattern — if `LabelSettingsPage` fetches both `fetchLabel` and `fetchLabels` in a `Promise.all`, the migration may need to keep the label-specific fetch while replacing only the labels-list fetch.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx src/pages/__tests__/LabelsPage.test.tsx src/components/editor/__tests__/LabelInput.test.tsx src/pages/__tests__/LabelCreatePage.test.tsx src/pages/__tests__/LabelSettingsPage.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate all 5 components**

**FilterPanel:** Replace `fetchLabels()` + `allLabels` state + `labelLoadError` state + `useEffect` with:
```tsx
const { data: allLabels = [], error: labelLoadErr } = useLabels()
const labelLoadError = labelLoadErr ? 'Failed to load labels' : null
```

**LabelsPage (LabelListView):** Replace `fetchLabels()` pattern with:
```tsx
const { data: labels = [], error, isLoading: loading } = useLabels()
const errorMsg = error
  ? error instanceof HTTPError && error.response.status === 401
    ? 'Session expired. Please log in again.'
    : 'Failed to load labels. Please try again later.'
  : null
```

**LabelInput:** Replace `fetchLabels()` pattern with:
```tsx
const { data: allLabels = [], error: labelsError } = useLabels()
const loadError = !!labelsError
```

**LabelCreatePage:** Replace `fetchLabels()` fetch with `useLabels()`. The `isReady` guard can be removed since SWR handles initial loading state.

**LabelSettingsPage:** Replace `fetchLabels()` within the `Promise.all` with `useLabels()`. The `fetchLabel(labelId)` part may need to stay as a separate effect or become its own hook call. Simplest: use `useLabels()` for the list, keep `fetchLabel` in a useEffect for the specific label data.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx src/pages/__tests__/LabelsPage.test.tsx src/components/editor/__tests__/LabelInput.test.tsx src/pages/__tests__/LabelCreatePage.test.tsx src/pages/__tests__/LabelSettingsPage.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/filters/FilterPanel.tsx frontend/src/pages/LabelsPage.tsx frontend/src/components/editor/LabelInput.tsx frontend/src/pages/LabelCreatePage.tsx frontend/src/pages/LabelSettingsPage.tsx
git add frontend/src/components/filters/__tests__/ frontend/src/pages/__tests__/LabelsPage.test.tsx frontend/src/components/editor/__tests__/ frontend/src/pages/__tests__/LabelCreatePage.test.tsx frontend/src/pages/__tests__/LabelSettingsPage.test.tsx
git commit -m "refactor: migrate label consumers to useLabels SWR hook"
```

---

## Task 11: Migrate social account consumers (EditorPage, CrossPostSection, SocialAccountsPanel)

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`
- Modify: `frontend/src/components/crosspost/CrossPostSection.tsx`
- Modify: `frontend/src/components/crosspost/SocialAccountsPanel.tsx`
- Modify: corresponding test files

- [ ] **Step 1: Update test mocks for all 3 components**

Mock `@/hooks/useSocialAccounts` in each test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx src/components/crosspost/__tests__/CrossPostSection.test.tsx src/components/crosspost/__tests__/SocialAccountsPanel.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate all 3 components**

**EditorPage:** Replace the `fetchSocialAccounts()` useEffect with:
```tsx
const { data: accounts = [], error: socialAccountsErr } = useSocialAccounts()
const socialAccountsError = socialAccountsErr
  ? await extractErrorDetail(socialAccountsErr, 'Failed to load connected social accounts. Please try again.')
  : null
```
Note: `extractErrorDetail` is async. Since SWR error is synchronous, derive the error message synchronously or simplify to a static string.

**CrossPostSection:** Replace the accounts fetch with `useSocialAccounts()`. History fetch becomes `useCrossPostHistory(filePath)`. The draft check (`if post.is_draft`) can be handled by passing `null` key when draft.

**SocialAccountsPanel:** Replace `loadAccounts()` + useEffect with `useSocialAccounts()`. Use `mutate` from the hook after `deleteSocialAccount` and social account authorization flows to refresh the list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx src/components/crosspost/__tests__/CrossPostSection.test.tsx src/components/crosspost/__tests__/SocialAccountsPanel.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx frontend/src/components/crosspost/CrossPostSection.tsx frontend/src/components/crosspost/SocialAccountsPanel.tsx
git add frontend/src/pages/__tests__/EditorPage.test.tsx frontend/src/components/crosspost/__tests__/
git commit -m "refactor: migrate social account consumers to useSocialAccounts SWR hook"
```

---

## Task 12: Migrate remaining pages (LabelGraphPage, LabelPostsPage, PageViewPage)

**Files:**
- Modify: `frontend/src/pages/LabelGraphPage.tsx`
- Modify: `frontend/src/pages/LabelPostsPage.tsx`
- Modify: `frontend/src/pages/PageViewPage.tsx`
- Modify: corresponding test files

- [ ] **Step 1: Update test mocks**

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelGraphPage.test.tsx src/pages/__tests__/LabelPostsPage.test.tsx src/pages/__tests__/PageViewPage.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate all 3 pages**

**LabelGraphPage:** Replace `fetchLabelGraph()` fetch with `useLabelGraph()`. Keep mutation logic (onConnect, onEdgeClick) as direct API calls that call `mutate()` to refresh the graph data after.

**LabelPostsPage:** Replace the `Promise.all([fetchLabel, fetchLabelPosts])` with `useLabelPosts(labelId)`. The hook returns `{ label, posts }` as a composite.

**PageViewPage:** Replace the `api.get('pages/${pageId}')` with `usePage(pageId)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelGraphPage.test.tsx src/pages/__tests__/LabelPostsPage.test.tsx src/pages/__tests__/PageViewPage.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LabelGraphPage.tsx frontend/src/pages/LabelPostsPage.tsx frontend/src/pages/PageViewPage.tsx
git add frontend/src/pages/__tests__/
git commit -m "refactor: migrate LabelGraphPage, LabelPostsPage, PageViewPage to SWR hooks"
```

---

## Task 13: Migrate FileStrip to usePostAssets

**Files:**
- Modify: `frontend/src/components/editor/FileStrip.tsx`
- Modify: `frontend/src/components/editor/__tests__/FileStrip.test.tsx`

- [ ] **Step 1: Update test mocks**

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/FileStrip.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate FileStrip**

Replace `fetchPostAssets` + `loadAssets` callback + useEffect with `usePostAssets(filePath)`. After delete/rename operations, call `mutate()` to revalidate instead of manually calling `loadAssets()`.

The `refreshToken` prop (used to trigger refetch after uploads) can be included in the SWR key or trigger `mutate()` via a useEffect.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/FileStrip.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/FileStrip.tsx frontend/src/components/editor/__tests__/FileStrip.test.tsx
git commit -m "refactor: migrate FileStrip to usePostAssets SWR hook"
```

---

## Task 14: Migrate AnalyticsPanel to SWR hooks

**Files:**
- Modify: `frontend/src/components/admin/AnalyticsPanel.tsx`
- Modify: `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx`

- [ ] **Step 1: Update test mocks**

Replace direct API mocks with hook mocks for `useAnalyticsDashboard` and `usePathReferrers`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/AnalyticsPanel.test.tsx --reporter=verbose`

- [ ] **Step 3: Migrate AnalyticsPanel**

This is the most complex migration. Replace:
- All 15+ state variables for dashboard data with `useAnalyticsDashboard(dateRange)`
- The referrer fetch with `usePathReferrers(selectedPath?.path_id ?? null)`
- The `loadDashboard` function is no longer needed — changing `dateRange` changes the SWR key, which triggers a refetch automatically
- `handleToggle` stays as a direct API call; after success, call `dashboardMutate()` to refresh

The component simplifies significantly:
```tsx
const [dateRange, setDateRange] = useState<DateRange>('7d')
const [selectedPath, setSelectedPath] = useState<{ path: string; path_id: number } | null>(null)
const [saving, setSaving] = useState(false)
const [saveError, setSaveError] = useState<string | null>(null)

const { data, error, isLoading: loading, mutate: dashboardMutate } = useAnalyticsDashboard(dateRange)
const { data: referrerData, error: referrerError, isLoading: referrersLoading } = usePathReferrers(selectedPath?.path_id ?? null)

const unavailable = !!error && !(error instanceof HTTPError && error.response.status === 401)
const settings = data?.settings ?? { analytics_enabled: false, show_views_on_posts: false }
const sortedPaths = useMemo(...)  // from Task 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/AnalyticsPanel.test.tsx --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/AnalyticsPanel.tsx frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx
git commit -m "refactor: migrate AnalyticsPanel to SWR hooks"
```

---

## Task 15: Full test suite and static checks

- [ ] **Step 1: Run full check gate**

```bash
just check
```

Fix any failures (type errors, lint errors, test failures).

- [ ] **Step 2: Commit any remaining fixes**

Stage only the specific files that needed fixing:

```bash
git add <specific files that were fixed>
git commit -m "fix: resolve lint and type errors from SWR migration"
```

---

## Task 16: Clean up unused imports and dead code

- [ ] **Step 1: Check for unused API function imports**

After migration, some components may still import API functions they no longer call directly. Run `knip` to find unused exports:

```bash
cd frontend && npm run lint:unused
```

- [ ] **Step 2: Remove unused imports**

Clean up any components that still import `fetchLabels`, `fetchSocialAccounts`, `fetchPost`, `fetchViewCount`, etc. when they now use hooks instead.

- [ ] **Step 3: Run full check gate**

```bash
just check
```

- [ ] **Step 4: Commit**

Stage only the cleaned-up files:

```bash
git add <specific files that were cleaned>
git commit -m "chore: remove unused imports after SWR migration"
```

---

## Task 17: Update architecture docs

**Files:**
- Modify: `docs/arch/frontend.md`

The SWR migration is a significant frontend architecture change. The architecture docs must be updated.

- [ ] **Step 1: Update frontend architecture doc**

In `docs/arch/frontend.md`, add a section describing the data-fetching layer:
- SWR is the standard for read-only data fetching
- Hooks in `frontend/src/hooks/` wrap SWR for each resource
- `SWRConfig` in `App.tsx` provides the global fetcher
- Shared hooks (`useLabels`, `useSocialAccounts`) deduplicate across components
- Mutations (writes) still use direct API calls, followed by `mutate()` for revalidation
- Components NOT migrated (debounced search, mutations-only) still use manual patterns

- [ ] **Step 2: Commit**

```bash
git add docs/arch/frontend.md
git commit -m "docs: update frontend architecture for SWR data-fetching layer"
```

---

## Parallelization Guide

Tasks that can run in parallel (independent of each other):

- **Tasks 3, 4, 5, 6, 7** — all hook creation tasks are independent (different files, different tests)
- **Tasks 8, 9** — PostPage and AdminPage migrations are independent
- **Tasks 10, 11** — label consumers and social account consumers are independent
- **Tasks 12, 13** — remaining pages and FileStrip are independent

Sequential dependencies:
- Task 1 → Task 14 (AnalyticsPanel review fixes must land before SWR migration of same component)
- Task 2 → Tasks 3-7 (SWR infrastructure must exist before hooks)
- Tasks 3-7 → Tasks 8-14 (hooks must exist before component migrations)
- Tasks 8-14 → Task 15 (all migrations before full test suite)
- Task 15 → Task 16 (fix errors before cleanup)
- Task 16 → Task 17 (cleanup before docs update)
