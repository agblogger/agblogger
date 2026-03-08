# Filter Header Relocation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the filter toggle button from FilterPanel into the Header toolbar, next to the search icon, with conditional rendering on the timeline page only.

**Architecture:** Create a small Zustand store (`useFilterPanelStore`) to share panel open/close state between Header (trigger) and FilterPanel (panel body). FilterPanel loses its toggle button and becomes externally controlled. Header gains a conditional filter icon with active-filter count badge.

**Tech Stack:** React, Zustand, Lucide icons, Tailwind CSS, Vitest + Testing Library

---

### Task 1: Create useFilterPanelStore

**Files:**
- Create: `frontend/src/stores/filterPanelStore.ts`
- Test: `frontend/src/stores/__tests__/filterPanelStore.test.ts`

**Step 1: Write the failing test**

Create `frontend/src/stores/__tests__/filterPanelStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useFilterPanelStore } from '../filterPanelStore'

describe('filterPanelStore', () => {
  beforeEach(() => {
    useFilterPanelStore.setState({
      panelState: 'closed',
      activeFilterCount: 0,
    })
  })

  it('starts closed with zero active filters', () => {
    const state = useFilterPanelStore.getState()
    expect(state.panelState).toBe('closed')
    expect(state.activeFilterCount).toBe(0)
  })

  it('togglePanel opens from closed', () => {
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('togglePanel starts closing from open', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closing')
  })

  it('togglePanel opens from closing (re-open during animation)', () => {
    useFilterPanelStore.setState({ panelState: 'closing' })
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('closePanel transitions open to closing', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().closePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closing')
  })

  it('closePanel is a no-op when already closed', () => {
    useFilterPanelStore.getState().closePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closed')
  })

  it('onAnimationEnd transitions closing to closed', () => {
    useFilterPanelStore.setState({ panelState: 'closing' })
    useFilterPanelStore.getState().onAnimationEnd()
    expect(useFilterPanelStore.getState().panelState).toBe('closed')
  })

  it('onAnimationEnd is a no-op when open', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().onAnimationEnd()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('setActiveFilterCount updates count', () => {
    useFilterPanelStore.getState().setActiveFilterCount(3)
    expect(useFilterPanelStore.getState().activeFilterCount).toBe(3)
  })
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/stores/__tests__/filterPanelStore.test.ts`
Expected: FAIL — module not found

**Step 3: Write the store**

Create `frontend/src/stores/filterPanelStore.ts`:

```ts
import { create } from 'zustand'

type PanelState = 'closed' | 'open' | 'closing'

interface FilterPanelState {
  panelState: PanelState
  activeFilterCount: number
  togglePanel: () => void
  closePanel: () => void
  onAnimationEnd: () => void
  setActiveFilterCount: (count: number) => void
}

export const useFilterPanelStore = create<FilterPanelState>((set, get) => ({
  panelState: 'closed',
  activeFilterCount: 0,

  togglePanel: () => {
    const current = get().panelState
    if (current === 'closed' || current === 'closing') {
      set({ panelState: 'open' })
    } else {
      set({ panelState: 'closing' })
    }
  },

  closePanel: () => {
    if (get().panelState === 'open') {
      set({ panelState: 'closing' })
    }
  },

  onAnimationEnd: () => {
    if (get().panelState === 'closing') {
      set({ panelState: 'closed' })
    }
  },

  setActiveFilterCount: (count: number) => set({ activeFilterCount: count }),
}))
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/stores/__tests__/filterPanelStore.test.ts`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add frontend/src/stores/filterPanelStore.ts frontend/src/stores/__tests__/filterPanelStore.test.ts
git commit -m "feat: add filterPanelStore for shared filter panel state"
```

---

### Task 2: Refactor FilterPanel to use external state

**Files:**
- Modify: `frontend/src/components/filters/FilterPanel.tsx`
- Modify: `frontend/src/components/filters/__tests__/FilterPanel.test.tsx`

**Step 1: Update FilterPanel tests to mock the store**

The FilterPanel will no longer manage its own panelState or render a toggle button. It reads `panelState`, `closePanel`, and `onAnimationEnd` from the store. It still receives `value` and `onChange` as props. It computes activeFilterCount and syncs it to the store via `setActiveFilterCount`.

Update the test file to:
- Mock `@/stores/filterPanelStore`
- Remove tests that click "Filters" toggle button (that moves to Header)
- Instead, set `mockPanelState = 'open'` to test panel contents
- Keep all tests for filter functionality (label toggle, search, chips, clear, etc.)
- Add a test that `setActiveFilterCount` is called with the correct count

Key test changes:
- Replace `await user.click(screen.getByText('Filters'))` with setting `mockPanelState = 'open'` and re-rendering
- The "renders Filters button" test becomes "does not render a toggle button"
- Add test: "calls setActiveFilterCount with correct count"
- Tests for chip area remain unchanged (they work when panel is closed)
- The "closes panel via Close button" test should verify `mockClosePanel` was called

**Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx`
Expected: FAIL — FilterPanel still has its own toggle button

**Step 3: Refactor FilterPanel**

Remove from `FilterPanel.tsx`:
- The `panelState` local state (replaced by store)
- The `togglePanel` function
- The `closePanel` function
- The `handleAnimationEnd` callback
- The toggle button JSX (lines 87–100)

Add to `FilterPanel.tsx`:
- Import `useFilterPanelStore`
- Read `panelState`, `closePanel`, `onAnimationEnd`, `setActiveFilterCount` from store
- `useEffect` to sync `activeFilterCount` to the store whenever `value` changes
- Derive `expanded = panelState === 'open'` from store

The component keeps:
- `allLabels` state + `fetchLabels` effect
- `labelSearch` local state
- `filteredLabels` memo
- `toggleLabel`, `clearAll` helpers
- Chip area JSX (visible when `!expanded && hasActive`)
- Panel body JSX (labels, date, author, actions)
- The `value` / `onChange` props interface

**Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/filters/__tests__/FilterPanel.test.tsx`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/components/filters/FilterPanel.tsx frontend/src/components/filters/__tests__/FilterPanel.test.tsx
git commit -m "refactor: make FilterPanel use external store for panel state"
```

---

### Task 3: Add filter icon to Header

**Files:**
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/components/layout/__tests__/Header.test.tsx`

**Step 1: Write failing Header tests**

Add these tests to `Header.test.tsx`:

```ts
// Mock the filter panel store
let mockPanelState = 'closed'
let mockActiveFilterCount = 0
const mockTogglePanel = vi.fn()

vi.mock('@/stores/filterPanelStore', () => ({
  useFilterPanelStore: (selector: (s: {
    panelState: string
    activeFilterCount: number
    togglePanel: () => void
  }) => unknown) =>
    selector({
      panelState: mockPanelState,
      activeFilterCount: mockActiveFilterCount,
      togglePanel: mockTogglePanel,
    }),
}))

// Add to beforeEach:
mockPanelState = 'closed'
mockActiveFilterCount = 0
vi.clearAllMocks()

// New tests:
it('shows filter icon on timeline page', () => {
  renderHeader('/')
  expect(screen.getByLabelText('Toggle filters')).toBeInTheDocument()
})

it('hides filter icon on non-timeline pages', () => {
  renderHeader('/labels')
  expect(screen.queryByLabelText('Toggle filters')).not.toBeInTheDocument()
})

it('hides filter icon on search page', () => {
  renderHeader('/search')
  expect(screen.queryByLabelText('Toggle filters')).not.toBeInTheDocument()
})

it('shows active filter count badge', () => {
  mockActiveFilterCount = 3
  renderHeader('/')
  expect(screen.getByText('3', { selector: '.rounded-full' })).toBeInTheDocument()
})

it('does not show badge when no active filters', () => {
  mockActiveFilterCount = 0
  renderHeader('/')
  expect(screen.queryByText('0', { selector: '.rounded-full' })).not.toBeInTheDocument()
})

it('calls togglePanel when filter icon is clicked', async () => {
  renderHeader('/')
  await userEvent.click(screen.getByLabelText('Toggle filters'))
  expect(mockTogglePanel).toHaveBeenCalledTimes(1)
})

it('filter icon has active style when panel is open', () => {
  mockPanelState = 'open'
  renderHeader('/')
  const btn = screen.getByLabelText('Toggle filters')
  expect(btn.className).toContain('text-accent')
})
```

**Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/layout/__tests__/Header.test.tsx`
Expected: FAIL — no "Toggle filters" button exists yet

**Step 3: Add filter icon to Header**

In `Header.tsx`:
- Import `Filter` from `lucide-react`
- Import `useFilterPanelStore`
- Read `panelState`, `activeFilterCount`, `togglePanel` from store
- Derive `isTimeline = location.pathname === '/'`
- Add filter button between search and theme toggle:

```tsx
{isTimeline && (
  <button
    onClick={togglePanel}
    className={`p-2 rounded-lg transition-colors ${
      panelState === 'open'
        ? 'text-accent bg-accent/10'
        : 'text-muted hover:text-ink hover:bg-paper-warm'
    }`}
    aria-label="Toggle filters"
    title="Filters"
  >
    <div className="relative">
      <Filter size={18} />
      {activeFilterCount > 0 && (
        <span className="absolute -top-1.5 -right-2 bg-accent text-white text-[9px] font-mono min-w-[16px] h-4 flex items-center justify-center px-1 rounded-full leading-none">
          {activeFilterCount}
        </span>
      )}
    </div>
  </button>
)}
```

Also add filter icon in mobile menu (when on timeline page), in the action buttons area.

**Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/layout/__tests__/Header.test.tsx`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/components/layout/Header.tsx frontend/src/components/layout/__tests__/Header.test.tsx
git commit -m "feat: add filter toggle icon to header toolbar"
```

---

### Task 4: Connect TimelinePage to store

**Files:**
- Modify: `frontend/src/pages/TimelinePage.tsx`

**Step 1: Verify current state**

Run: `cd frontend && npx vitest run`
Expected: All tests pass (FilterPanel and Header tests already updated in Tasks 2–3)

**Step 2: Update TimelinePage**

In `TimelinePage.tsx`:
- Import `useFilterPanelStore`
- Read `setActiveFilterCount` from store
- Add `useEffect` to sync active filter count to the store based on `filterState`:

```ts
const setActiveFilterCount = useFilterPanelStore((s) => s.setActiveFilterCount)

useEffect(() => {
  const count =
    filterState.labels.length +
    (filterState.author ? 1 : 0) +
    (filterState.fromDate ? 1 : 0) +
    (filterState.toDate ? 1 : 0)
  setActiveFilterCount(count)
}, [filterState.labels, filterState.author, filterState.fromDate, filterState.toDate, setActiveFilterCount])
```

Note: This count sync was previously inside FilterPanel. Now TimelinePage is the owner of filter state, so it syncs the count. Remove the equivalent logic from FilterPanel if it was moved there in Task 2.

**Step 3: Run all tests**

Run: `cd frontend && npx vitest run`
Expected: All tests pass

**Step 4: Commit**

```bash
git add frontend/src/pages/TimelinePage.tsx
git commit -m "feat: sync active filter count from TimelinePage to store"
```

---

### Task 5: Visual verification and cleanup

**Step 1: Start dev server**

Run: `just start`

**Step 2: Browser test with Playwright MCP**

Verify:
1. Navigate to `/` — filter icon visible in header, next to search icon
2. Click filter icon — panel opens below tabs
3. Click filter icon again — panel closes
4. Select a label filter — badge appears on filter icon with count "1"
5. Navigate to `/labels` — filter icon disappears from header
6. Navigate back to `/` — filter icon reappears, badge still shows if filters active
7. Open search — search input appears, filter icon still visible
8. Mobile: filter icon visible in mobile view header or mobile menu

**Step 3: Run full check**

Run: `just check`
Expected: All static checks and tests pass

**Step 4: Commit any tweaks, then stop dev server**

```bash
just stop
```

---

### Task 6: Update architecture docs

**Files:**
- Modify: `docs/arch/frontend.md`

**Step 1: Update frontend.md**

Add/update the section on filter panel state management:
- Mention the `useFilterPanelStore` Zustand store
- Note that the filter trigger lives in Header (conditional on timeline route)
- Note that FilterPanel body lives in TimelinePage
- Update the component hierarchy if documented

**Step 2: Commit**

```bash
git add docs/arch/frontend.md
git commit -m "docs: update frontend arch for filter header relocation"
```
