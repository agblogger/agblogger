# Label Detail Page Hierarchy Display — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show clickable children and parents on the label detail page (`/labels/:labelId`).

**Architecture:** Frontend-only change to `LabelPostsPage.tsx`. Add two optional sections (children, then parents) between the header/aliases block and the post list. Reuse `LabelChip` for children and `Link` for parents. `LabelResponse` already carries `parents` and `children` arrays — no backend changes.

**Tech Stack:** React, react-router-dom `Link`, existing `LabelChip` component, Tailwind CSS, Vitest + React Testing Library.

**Spec:** `docs/specs/2026-03-15-label-detail-hierarchy-design.md`

---

## Chunk 1: Tests and Implementation

### Task 1: Write failing tests for hierarchy display

**Files:**
- Modify: `frontend/src/pages/__tests__/LabelPostsPage.test.tsx`

The existing `testLabel` fixture has `parents: ['cs'], children: []`. Change the default fixture to `parents: []` so existing tests don't inadvertently render a Parents section. The new hierarchy-specific tests use their own fixtures with explicit parent/child values.

- [ ] **Step 1: Update testLabel fixture**

Change `parents: ['cs']` to `parents: []` in the `testLabel` constant so existing tests don't inadvertently render hierarchy sections:

```tsx
const testLabel: LabelResponse = {
  id: 'swe',
  names: ['software engineering'],
  is_implicit: false,
  parents: [],
  children: [],
  post_count: 2,
}
```

- [ ] **Step 2: Add LabelChip mock**

Add a `vi.mock` for `LabelChip` after the existing `PostCard` mock (follows the project convention used in `PostPage.test.tsx:38-40`):

```tsx
vi.mock('@/components/labels/LabelChip', () => ({
  default: ({ labelId }: { labelId: string }) => (
    <a data-testid="label-chip" href={`/labels/${labelId}`}>#{labelId}</a>
  ),
}))
```

- [ ] **Step 3: Add four test cases**

Add these tests inside the existing `describe('LabelPostsPage', ...)` block, after the last existing test:

```tsx
it('renders children as clickable chips', async () => {
  const labelWithChildren: LabelResponse = {
    ...testLabel,
    children: ['frontend', 'backend'],
    parents: [],
  }
  mockFetchLabel.mockResolvedValue(labelWithChildren)
  mockFetchLabelPosts.mockResolvedValue(postsData)
  renderPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })
  expect(screen.getByText('Children')).toBeInTheDocument()
  const chips = screen.getAllByTestId('label-chip')
  expect(chips).toHaveLength(2)
  expect(chips[0]).toHaveAttribute('href', '/labels/frontend')
  expect(chips[1]).toHaveAttribute('href', '/labels/backend')
})

it('renders parents as clickable links', async () => {
  const labelWithParents: LabelResponse = {
    ...testLabel,
    children: [],
    parents: ['cs', 'engineering'],
  }
  mockFetchLabel.mockResolvedValue(labelWithParents)
  mockFetchLabelPosts.mockResolvedValue(postsData)
  renderPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })
  expect(screen.getByText('Parents')).toBeInTheDocument()
  const csLink = screen.getByRole('link', { name: '#cs' })
  expect(csLink).toHaveAttribute('href', '/labels/cs')
  const engLink = screen.getByRole('link', { name: '#engineering' })
  expect(engLink).toHaveAttribute('href', '/labels/engineering')
})

it('renders both children and parents with children first', async () => {
  const labelWithBoth: LabelResponse = {
    ...testLabel,
    children: ['frontend'],
    parents: ['cs'],
  }
  mockFetchLabel.mockResolvedValue(labelWithBoth)
  mockFetchLabelPosts.mockResolvedValue(postsData)
  renderPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })
  const childrenHeading = screen.getByText('Children')
  const parentsHeading = screen.getByText('Parents')
  // Children section appears before Parents in the DOM
  expect(
    childrenHeading.compareDocumentPosition(parentsHeading) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

it('renders no hierarchy sections when label has no parents or children', async () => {
  const labelNoHierarchy: LabelResponse = {
    ...testLabel,
    children: [],
    parents: [],
  }
  mockFetchLabel.mockResolvedValue(labelNoHierarchy)
  mockFetchLabelPosts.mockResolvedValue(postsData)
  renderPage()

  await waitFor(() => {
    expect(screen.getByText('#swe')).toBeInTheDocument()
  })
  expect(screen.queryByText('Children')).not.toBeInTheDocument()
  expect(screen.queryByText('Parents')).not.toBeInTheDocument()
})
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `just test-frontend`
Expected: 4 new tests FAIL (headings "Children"/"Parents" not found in the DOM).

- [ ] **Step 5: Commit failing tests**

```bash
git add frontend/src/pages/__tests__/LabelPostsPage.test.tsx
git commit -m "test: add failing tests for label detail hierarchy display"
```

---

### Task 2: Implement hierarchy sections in LabelPostsPage

**Files:**
- Modify: `frontend/src/pages/LabelPostsPage.tsx`

- [ ] **Step 1: Add LabelChip and Link imports**

`LabelChip` needs to be imported. `Link` is already imported.

Add at the top of the file, after the existing imports:

```tsx
import LabelChip from '@/components/labels/LabelChip'
```

- [ ] **Step 2: Compute whether hierarchy sections exist**

Inside the JSX return, after the aliases `<p>` block and before the post list, we need to determine if hierarchy sections should render. We also need to conditionally control `mb-8` on aliases.

Derive a boolean for whether any hierarchy is present:

```tsx
const hasHierarchy =
  label !== null && (label.children.length > 0 || label.parents.length > 0)
```

Place this in the component body, after the early-return guards for loading (line 43-45) and error (line 47-56), and before the main JSX `return` on line 58.

- [ ] **Step 3: Update aliases margin to be conditional**

Change the aliases `<p>` (currently line 84) from:

```tsx
<p className="text-muted mb-8">{label.names.join(', ')}</p>
```

to:

```tsx
<p className={`text-muted${hasHierarchy ? '' : ' mb-8'}`}>{label.names.join(', ')}</p>
```

This removes `mb-8` from aliases when hierarchy sections follow.

- [ ] **Step 4: Add hierarchy sections JSX**

Insert the following JSX block after the aliases `<p>` closing tag and before the post list (`{!data || data.posts.length === 0 ?` block):

```tsx
{label !== null && label.children.length > 0 && (
  <div className={`mt-4${label.parents.length > 0 ? '' : ' mb-8'}`}>
    <h2 className="text-sm font-medium text-muted mb-2">Children</h2>
    <div className="flex flex-wrap gap-2">
      {label.children.map((c) => (
        <LabelChip key={c} labelId={c} />
      ))}
    </div>
  </div>
)}

{label !== null && label.parents.length > 0 && (
  <div className={`${label.children.length > 0 ? 'mt-3' : 'mt-4'} mb-8`}>
    <h2 className="text-sm font-medium text-muted mb-2">Parents</h2>
    <div className="text-sm">
      {label.parents.map((p, idx) => (
        <span key={p}>
          {idx > 0 && ', '}
          <Link
            to={`/labels/${p}`}
            className="text-muted hover:text-ink underline decoration-border hover:decoration-ink transition-colors"
          >
            #{p}
          </Link>
        </span>
      ))}
    </div>
  </div>
)}
```

Spacing logic:
- Children section: `mt-4` always; `mb-8` only if no parents follow
- Parents section: `mt-3` if children precede it, `mt-4` if no children; always `mb-8` (it's always last)

- [ ] **Step 5: Handle mb-8 when hierarchy exists but no aliases**

When a label has no names (aliases block doesn't render) but has hierarchy, we need `mb-8` to still end up on the last hierarchy section. The logic in step 4 already handles this: children gets `mb-8` when it's the last section, parents always gets `mb-8`.

But we also need to handle the case where there are no aliases AND no hierarchy — the header's existing `mb-2` stands alone before posts. This is unchanged from current behavior since `mb-8` on the aliases conditional only applies when aliases exist.

No additional changes needed — verify the edge case passes in tests.

- [ ] **Step 6: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All tests PASS, including the 4 new hierarchy tests.

- [ ] **Step 7: Commit implementation**

```bash
git add frontend/src/pages/LabelPostsPage.tsx
git commit -m "feat: show clickable children and parents on label detail page"
```

---

### Task 3: Verify full gate

- [ ] **Step 1: Run full check**

Run: `just check`
Expected: All static checks and tests pass.

- [ ] **Step 2: Manual browser test**

Start dev server with `just start`. Navigate to a label that has both parents and children. Verify:
- Children section appears with clickable chips
- Parents section appears with clickable links
- Clicking a child/parent navigates to that label's page
- Labels with no hierarchy show no extra sections

Stop dev server with `just stop`.
