# Labels Page Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add search filtering, children display, and clickable parent/child navigation to the label list view.

**Architecture:** All changes are in `LabelsPage.tsx` and its test file. Search state is lifted to `LabelsPage` so the header (title, search input, view toggle) stays at the top level and remains visible during loading/error/empty states. The search input is only rendered in list view. `LabelListView` receives `search` as a prop and uses `filterLabelsBySearch` to filter. No new files created.

**Tech Stack:** React, TypeScript, Vitest, React Testing Library, react-router-dom

**Spec:** `docs/specs/2026-03-15-labels-page-improvements-design.md`

---

## Chunk 1: Search Filtering

### Task 1: Add search filter tests and implementation

**Files:**
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Modify: `frontend/src/pages/__tests__/LabelsPage.test.tsx`

- [ ] **Step 1: Write failing tests for search filtering**

Add these tests to the existing `describe('LabelsPage', ...)` block in `frontend/src/pages/__tests__/LabelsPage.test.tsx`:

```tsx
it('filters labels by search input', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })

  await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'math')

  expect(screen.queryByText('#swe')).not.toBeInTheDocument()
  expect(screen.getByText('#math')).toBeInTheDocument()
})

it('shows empty message when search matches nothing', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })

  await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'zzzzz')

  expect(screen.queryByText('#swe')).not.toBeInTheDocument()
  expect(screen.queryByText('#math')).not.toBeInTheDocument()
  expect(screen.getByText('No labels match your search.')).toBeInTheDocument()
})

it('shows all labels when search is cleared', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })

  const searchInput = screen.getByPlaceholderText('Filter labels...')
  await userEvent.type(searchInput, 'math')
  expect(screen.queryByText('#swe')).not.toBeInTheDocument()

  await userEvent.clear(searchInput)
  expect(screen.getByText('#swe')).toBeInTheDocument()
  expect(screen.getByText('#math')).toBeInTheDocument()
})

it('filters labels by display name', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })

  await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'software')

  expect(screen.getByText('#swe')).toBeInTheDocument()
  expect(screen.queryByText('#math')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — placeholder "Filter labels..." not found

- [ ] **Step 3: Implement search filter in LabelsPage**

In `frontend/src/pages/LabelsPage.tsx`, make these changes:

**Add imports** at the top of the file:
```tsx
import { Search } from 'lucide-react'
import { filterLabelsBySearch } from '@/components/labels/searchUtils'
```

**Add search state** in `LabelsPage` component, after the `view` state:
```tsx
const [search, setSearch] = useState('')
```

**Replace the list view header** (lines 47-53). The current code:
```tsx
<div className="flex items-center justify-between mb-8">
  <div className="flex items-center gap-3">
    <Tag size={20} className="text-accent" />
    <h1 className="font-display text-3xl text-ink">Labels</h1>
  </div>
  {viewToggle}
</div>
```

Replace with:
```tsx
<div className="flex items-center justify-between mb-8">
  <div className="flex items-center gap-3">
    <Tag size={20} className="text-accent" />
    <h1 className="font-display text-3xl text-ink">Labels</h1>
  </div>
  <div className="flex items-center gap-3 ml-auto">
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Filter labels..."
        className="w-48 pl-9 pr-3 py-2 text-sm border border-border rounded-lg
          bg-paper focus:outline-none focus:border-accent/50 transition-colors"
      />
    </div>
    {viewToggle}
  </div>
</div>
```

**Pass `search` to `LabelListView`** — update the component call:
```tsx
<LabelListView search={search} />
```

**Update `LabelListView`** to accept and use `search` prop:
```tsx
function LabelListView({ search }: { search: string }) {
```

Add filtered labels after the existing state declarations (after `const [error, setError] = ...`):
```tsx
const filteredLabels = filterLabelsBySearch(labels, search)
```

After the `labels.length === 0` early return, replace the grid `return` block. The current code (lines 100-156):
```tsx
return (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
    {labels.map((label, i) => (
      // ... card markup ...
    ))}
  </div>
)
```

Replace with:
```tsx
if (filteredLabels.length === 0) {
  return <p className="text-muted text-center py-16">No labels match your search.</p>
}

return (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
    {filteredLabels.map((label, i) => (
      // ... keep existing card markup exactly as-is, just change labels.map to filteredLabels.map ...
    ))}
  </div>
)
```

The card markup inside the `.map()` stays identical. The only change is `labels.map` → `filteredLabels.map` and the new empty-filter guard above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All tests PASS (including existing tests — the header stays in `LabelsPage` so heading/toggle are always visible)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LabelsPage.tsx frontend/src/pages/__tests__/LabelsPage.test.tsx
git commit -m "feat: add search filter to labels list view"
```

---

## Chunk 2: Children & Parents Display

### Task 2: Update test fixtures and add children display

**Files:**
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Modify: `frontend/src/pages/__tests__/LabelsPage.test.tsx`

- [ ] **Step 1: Update test fixtures, migrate existing selectors, and write failing tests for children display**

In `frontend/src/pages/__tests__/LabelsPage.test.tsx`:

**A. Add `within` import** — update the testing-library import:
```tsx
import { render, screen, waitFor, within } from '@testing-library/react'
```

**B. Update `sampleLabels`** to include children and a parent label:

```tsx
const sampleLabels: LabelResponse[] = [
  {
    id: 'cs',
    names: ['computer science'],
    is_implicit: false,
    parents: [],
    children: ['swe', 'math'],
    post_count: 10,
  },
  {
    id: 'swe',
    names: ['software engineering'],
    is_implicit: false,
    parents: ['cs'],
    children: [],
    post_count: 5,
  },
  {
    id: 'math',
    names: ['mathematics'],
    is_implicit: false,
    parents: ['cs'],
    children: [],
    post_count: 3,
  },
]
```

**C. Add a helper** to find a label card by its aria-label:
```tsx
function getCardByLabel(labelId: string): HTMLElement {
  return screen.getByLabelText(`Open label #${labelId}`).closest('div[class*="group"]') as HTMLElement
}
```

**D. Migrate existing tests** to use `within()` scoped queries instead of bare `getByText`. This prevents failures from duplicate text once child chips render label IDs as `LabelChip` text (e.g., `#swe` appears both as a card heading and as a child chip inside the `#cs` card).

Update `'renders labels in list view by default'`:
```tsx
it('renders labels in list view by default', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(within(getCardByLabel('swe')).getByText('#swe')).toBeInTheDocument()
  })
  expect(within(getCardByLabel('math')).getByText('#math')).toBeInTheDocument()
  expect(within(getCardByLabel('swe')).getByText('5 posts')).toBeInTheDocument()
  expect(within(getCardByLabel('math')).getByText('3 posts')).toBeInTheDocument()
})
```

Update `'switches to graph view when Graph button is clicked'` — the `waitFor` uses `getByText('#swe')` which will match multiple elements after children render. Fix the initial wait, keep the `queryByText` absence check:
```tsx
// Replace: expect(screen.getByText('#swe')).toBeInTheDocument()
// With:
expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
// The queryByText('#swe') asserting absence after switching to graph is safe (both gone)
```

Update `'shows empty message when search matches nothing'` — same issue with `getByText('#swe')` in `waitFor`:
```tsx
// Replace: expect(screen.getByText('#swe')).toBeInTheDocument()
// With:
expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
```

Update `'switches back to list view when List button is clicked'` — the `getByText('#swe')` in `waitFor` may match multiple elements. Fix:
```tsx
// Replace: expect(screen.getByText('#swe')).toBeInTheDocument()
// With:
expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
```

Update `'filters labels by search input'`:
```tsx
it('filters labels by search input', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  })

  await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'math')

  expect(screen.queryByLabelText('Open label #swe')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
})
```

Update `'shows all labels when search is cleared'`:
```tsx
it('shows all labels when search is cleared', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  })

  const searchInput = screen.getByPlaceholderText('Filter labels...')
  await userEvent.type(searchInput, 'math')
  expect(screen.queryByLabelText('Open label #swe')).not.toBeInTheDocument()

  await userEvent.clear(searchInput)
  expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
})
```

Update `'filters labels by display name'`:
```tsx
it('filters labels by display name', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  })

  await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'software')

  expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  expect(screen.queryByLabelText('Open label #math')).not.toBeInTheDocument()
})
```

**E. Add the failing children display tests:**

```tsx
it('displays children as clickable chips', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #cs')).toBeInTheDocument()
  })

  const csCard = getCardByLabel('cs')
  const childLinks = csCard.querySelectorAll('a[href="/labels/swe"], a[href="/labels/math"]')
  expect(childLinks).toHaveLength(2)
})

it('does not show children chips when label has no children', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
  })

  // #math has no children — the only links should be the card overlay and possibly a parent link
  const mathCard = getCardByLabel('math')
  const allLinks = Array.from(mathCard.querySelectorAll('a'))
  const nonCardLinks = allLinks.filter(
    (a) => a.getAttribute('href') !== '/labels/math' && !a.getAttribute('href')?.includes('/settings'),
  )
  // Only parent link (/labels/cs) expected, no child chip links
  expect(nonCardLinks.every((a) => a.getAttribute('href') === '/labels/cs')).toBe(true)
})
```

- [ ] **Step 2: Run tests to verify the children tests fail**

Run: `just test-frontend`
Expected: FAIL — child links `a[href="/labels/swe"]` and `a[href="/labels/math"]` not found in `#cs` card

- [ ] **Step 3: Implement children display**

In `frontend/src/pages/LabelsPage.tsx`, add the `LabelChip` import:
```tsx
import LabelChip from '@/components/labels/LabelChip'
```

In the card markup inside `LabelListView`, after the closing `</div>` of the `flex items-start justify-between` block (after the names paragraph and post count badge) and **before** the parents section, add:

```tsx
{label.children.length > 0 && (
  <div className="mt-3 flex flex-wrap gap-1.5 pointer-events-auto relative z-10">
    {label.children.map((c) => (
      <LabelChip key={c} labelId={c} />
    ))}
  </div>
)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LabelsPage.tsx frontend/src/pages/__tests__/LabelsPage.test.tsx
git commit -m "feat: display children as clickable chips in label cards"
```

### Task 3: Update parents display

**Files:**
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Modify: `frontend/src/pages/__tests__/LabelsPage.test.tsx`

- [ ] **Step 1: Write failing tests for new parents display**

Add to the test file:

```tsx
it('displays parents as subtle clickable links', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
  })

  // The #swe card should show "in" text with a link to parent #cs
  const sweCard = getCardByLabel('swe')
  expect(sweCard.textContent).toContain('in')
  const parentLink = sweCard.querySelector('a[href="/labels/cs"]')
  expect(parentLink).not.toBeNull()
  expect(parentLink!.textContent).toBe('#cs')
})

it('does not show parents section when label has no parents', async () => {
  mockFetchLabels.mockResolvedValue(sampleLabels)
  renderLabelsPage()

  await waitFor(() => {
    expect(screen.getByLabelText('Open label #cs')).toBeInTheDocument()
  })

  // The #cs card has no parents — should not show "in" text
  const csCard = getCardByLabel('cs')
  const inSpan = Array.from(csCard.querySelectorAll('span')).find(
    (el) => el.textContent?.trim() === 'in',
  )
  expect(inSpan).toBeUndefined()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — the current parents display uses "Parent:"/"Parents:" not "in", and uses `<span>` not `<a>` for parent IDs

- [ ] **Step 3: Replace parents display with subtle links**

In `frontend/src/pages/LabelsPage.tsx`, find the existing parents section inside the card markup:

```tsx
{label.parents.length > 0 && (
  <div className="mt-3 flex items-center gap-1 text-xs text-muted">
    <span>{label.parents.length === 1 ? 'Parent:' : 'Parents:'}</span>
    {label.parents.map((p) => (
      <span key={p} className="text-tag-text bg-tag-bg px-1.5 py-0.5 rounded">
        #{p}
      </span>
    ))}
  </div>
)}
```

Replace with:

```tsx
{label.parents.length > 0 && (
  <div className="mt-2 text-xs text-muted pointer-events-auto relative z-10">
    <span>in </span>
    {label.parents.map((p, idx) => (
      <span key={p}>
        {idx > 0 && ', '}
        <Link
          to={`/labels/${p}`}
          className="text-muted hover:text-ink underline decoration-border hover:decoration-ink transition-colors"
          onClick={(e) => e.stopPropagation()}
        >
          #{p}
        </Link>
      </span>
    ))}
  </div>
)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All tests PASS

- [ ] **Step 5: Run full quality gate**

Run: `just check-frontend`
Expected: All static checks and tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LabelsPage.tsx frontend/src/pages/__tests__/LabelsPage.test.tsx
git commit -m "feat: show parents as subtle clickable links in label cards"
```

### Task 4: Final verification

- [ ] **Step 1: Run the full quality gate**

Run: `just check`
Expected: All checks PASS

- [ ] **Step 2: Manual browser verification**

Run: `just start`

Open the labels page in the browser. Verify:
1. Search input appears in the header next to the view toggle
2. Typing filters labels (hides non-matching), clearing restores all
3. "No labels match your search." appears for no-match queries
4. Children appear as clickable chips below label names
5. Clicking a child chip navigates to that label's posts page
6. Parents appear as subtle "in #parent" links below children
7. Clicking a parent link navigates to that label's posts page
8. The whole card is still clickable to navigate to the label's posts page
9. Settings link still works for authenticated users
10. Header (title, search, view toggle) remains visible during loading and error states

Run: `just stop`
