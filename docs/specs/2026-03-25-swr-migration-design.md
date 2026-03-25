# SWR Migration & Review Fixes Design

## Overview

Adopt SWR for project-wide data fetching and fix two Vercel React Best Practices review findings from the GoatCounter analytics PR. (The third finding — PostPage waterfall — is resolved naturally by the SWR migration since `usePost` and `useViewCount` fire independently in parallel.)

## Part 1: Review Fixes (no SWR)

Two standalone fixes in AnalyticsPanel:

1. **Sort in render**: `[...paths].sort(...)` is computed inline in JSX on every render. Extract to `useMemo(() => [...paths].sort(...), [paths])`. Derive `topPage` from the same memoized result instead of re-sorting separately.

2. **Initial load effect**: Replace `initialLoadRef` guard + effect with no dependency array with a simple `useEffect(() => { void loadDashboard('7d') }, [])`. The ref is unnecessary since the initial `dateRange` state is always `'7d'`.

## Part 2: SWR Infrastructure

### Installation

Add `swr` package (~4KB gzipped).

### SWRConfig provider

Wrap the application tree in `App.tsx` with `<SWRConfig>` providing the default fetcher and global options. This also enables cache isolation in tests via a provider wrapper.

```tsx
<SWRConfig value={{ fetcher: (url: string) => api.get(url).json(), dedupingInterval: 2000 }}>
  {/* existing app tree */}
</SWRConfig>
```

### SWR key convention

Keys are ky-relative URL paths (the same strings passed to `api.get()`). The global fetcher passes the key directly to `api.get(url).json()`. Examples:
- `'labels'` → `api.get('labels').json()`
- `'posts/my-slug'` → `api.get('posts/my-slug').json()`
- `'analytics/views/my-slug'` → `api.get('analytics/views/my-slug').json()`

For hooks with composite fetchers (multiple parallel calls), use an array key like `['analytics-dashboard', start, end]` with a custom fetcher function.

### Error handling

SWR's `error` value will be the raw ky `HTTPError` on 4xx/5xx responses. ky throws `HTTPError` before `.json()` runs on error status codes, so the existing error type is preserved. Components remain responsible for error classification (checking `error.response.status` for 401, 404, etc.) — the same pattern they use today. Hooks do not interpret errors.

## Part 3: SWR Hooks

All hooks live in `frontend/src/hooks/`.

### Shared data hooks (deduplication wins)

**`useLabels()`** — replaces `fetchLabels()` calls in FilterPanel, LabelsPage/LabelListView, LabelInput, LabelCreatePage, LabelSettingsPage (5 places).

**`useSocialAccounts()`** — replaces `fetchSocialAccounts()` calls in EditorPage, CrossPostSection, SocialAccountsPanel (3 places).

### Single-use read hooks (caching/boilerplate wins)

- **`usePost(slug)`** — PostPage
- **`useViewCount(slug)`** — PostPage (conditional on slug). Fires in parallel with `usePost` since SWR hooks are independent.
- **`useAdminSiteSettings()`** — AdminPage (site settings only)
- **`useAdminPages()`** — AdminPage (pages only). Split from settings so each can be independently revalidated after mutations.
- **`useLabelGraph()`** — LabelGraphPage
- **`useLabelPosts(labelId)`** — LabelPostsPage
- **`usePage(pageId)`** — PageViewPage
- **`usePostAssets(filePath, refreshToken)`** — FileStrip
- **`useCrossPostHistory(filePath)`** — CrossPostSection

### Analytics hooks

The AnalyticsPanel has three distinct data-fetching patterns:

- **`useAnalyticsDashboard(dateRange)`** — wraps the 5 parallel fetches (settings, stats, paths, browsers, OS) using `useSWR` with a custom fetcher and array key `['analytics-dashboard', start, end]`. These 5 calls always load together as a single view, so a composite cache entry is appropriate.
- **`usePathReferrers(pathId)`** — separate hook for the drill-down referrer fetch triggered by clicking a path row. `null` key when no path is selected.
- Settings toggle mutations (`handleToggle`) stay as direct API calls within the component. After a successful toggle, call `mutate()` on the dashboard key to refresh.

### Hook return shape

Each hook returns SWR's standard `{ data, error, isLoading, mutate }`. Components destructure what they need. Error messages are derived at the component level (e.g., `error ? 'Failed to load labels' : null`), with status-code checks where needed (`error instanceof HTTPError && error.response.status === 401`).

### Conditional fetching

Hooks accept nullable parameters. When `null`, the SWR key is `null` and no fetch occurs:
```tsx
useViewCount(slug ?? null)  // don't fetch until slug is available
usePathReferrers(selectedPathId)  // null when no path selected
```

### Mutation pattern

Components that write data (e.g., FileStrip deleting an asset) call `mutate()` from the hook to trigger SWR revalidation, replacing manual re-fetch logic.

## Part 4: Components NOT migrated

These stay as-is with manual useEffect+useState:

- **Header** — debounced search with dropdown interaction
- **SearchPage** — debounced search with URL params
- **TimelinePage** — paginated/filtered fetches with upload side effects
- **EditorPage preview** — render-on-body-change, not a data read
- **CrossPostDialog** — mutation only
- **SiteSettingsSection** — mutation only (form save)
- **PagesSection** — mutation only (CRUD)

## Part 5: Testing Strategy

- **Hook tests**: Each `use*` hook tested with `renderHook` + `<SWRConfig value={{ provider: () => new Map() }}>` wrapper for cache isolation. Verify: correct key construction, loading/error/data states, `null` key suppresses fetch.
- **Deduplication test**: `useLabels` renders two components simultaneously, verify single API call.
- **Mutate-after-write test**: FileStrip asset deletion triggers SWR revalidation.
- **Component tests**: Existing tests updated for SWR async timing (`waitFor` adjustments). User-facing behavior unchanged.
- No new E2E tests — behavior is identical from the user's perspective.
