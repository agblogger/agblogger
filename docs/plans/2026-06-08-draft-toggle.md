# Draft Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New posts default to draft, and the draft control becomes a styled `role="switch"` button matching the amber DRAFT badge style used on post cards and the post page.

**Architecture:** Both changes are confined to `frontend/src/pages/EditorPage.tsx` and its test file. The `isDraft` state initializer changes from `false` to `isNew`. The plain checkbox is replaced with a `<button role="switch" aria-checked={isDraft}>` toggle pill that has amber styling when draft is on and muted styling when draft is off.

**Tech Stack:** React, TypeScript, Tailwind CSS, Vitest + @testing-library/react

---

## Files

- Modify: `frontend/src/pages/EditorPage.tsx:46` (default state) and `:433–444` (toggle UI)
- Modify: `frontend/src/pages/__tests__/EditorPage.test.tsx` (tests updated/added throughout)

---

### Task 1: Update tests for the new draft default

The `isDraft` state will default to `true` for new posts. Several existing tests assume `false`; they need updating before the implementation changes. Changing tests first makes the failures explicit and intentional (TDD red step).

**Files:**
- Modify: `frontend/src/pages/__tests__/EditorPage.test.tsx`

- [ ] **Step 1: Update `creates new post on save` to expect `is_draft: true`**

In `EditorPage.test.tsx` find the test `creates new post on save` (~line 546). The `waitFor` block currently expects `is_draft: false`. Change it to `is_draft: true`:

```ts
await waitFor(() => {
  expect(mockCreatePost).toHaveBeenCalledWith({
    title: 'My Title',
    subtitle: null,
    body: '',
    labels: [],
    is_draft: true,   // changed: new posts default to draft
  })
})
```

- [ ] **Step 2: Update `draft checkbox toggles isDraft` — expect checked initially, clicking unchecks**

Find `draft checkbox toggles isDraft` (~line 721). New posts start as `isDraft=true`, so the control starts in the on/checked state. Update the test to reflect that (still using `checkbox` role for now — that will change in Task 2):

```ts
it('draft checkbox toggles isDraft', async () => {
  const user = userEvent.setup()
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  const checkbox = screen.getByRole('checkbox', { name: /draft/i })
  expect(checkbox).toBeChecked()     // changed: starts checked (draft by default)

  await user.click(checkbox)
  expect(checkbox).not.toBeChecked() // changed: click turns draft off
})
```

- [ ] **Step 3: Update `disables save-time cross-posting when the post is marked as draft` — new posts start as draft**

Find this test (~line 349). Previously it clicked the draft checkbox to turn draft ON. Now draft is on by default, so clicking once turns it OFF instead. Rewrite the test to verify the initial draft-on state disables cross-posting, and that toggling draft off re-enables it:

```ts
it('disables save-time cross-posting when the post is marked as draft', async () => {
  const user = userEvent.setup()
  mockFetchSocialAccounts.mockResolvedValue([
    {
      id: 1,
      platform: 'bluesky',
      account_name: 'alice.bsky.social',
      created_at: '2026-01-15T10:00:00Z',
    },
  ])

  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByText('Cross-post after saving:')).toBeInTheDocument()
  })

  // New post starts as draft — cross-posting should already be disabled
  const crossPostCheckbox = screen.getByRole('checkbox', { name: /alice\.bsky\.social/i })
  expect(crossPostCheckbox).toBeDisabled()
  expect(
    screen.getByText('Publish the post to enable cross-posting after saving.'),
  ).toBeInTheDocument()

  // Toggle draft off — cross-posting should become enabled
  const draftCheckbox = screen.getByRole('checkbox', { name: /draft/i })
  await user.click(draftCheckbox)
  expect(crossPostCheckbox).not.toBeDisabled()
  expect(
    screen.queryByText('Publish the post to enable cross-posting after saving.'),
  ).not.toBeInTheDocument()
})
```

- [ ] **Step 4: Update `does not open cross-post dialog when saving a draft with platforms selected`**

Find this test (~line 1214). Previously it checked bluesky (while draft=false), then toggled draft on. Now draft starts on, so the test must toggle draft off first to enable bluesky, check it, then toggle draft back on before saving:

```ts
it('does not open cross-post dialog when saving a draft with platforms selected', async () => {
  const mockCreatePost = vi.mocked(createPost)
  mockCreatePost.mockResolvedValue({
    id: 1,
    file_path: 'posts/2026-03-13-test/index.md',
    title: 'Test',
    subtitle: null,
    author: 'jane',
    created_at: '2026-03-13 12:00:00+00:00',
    modified_at: '2026-03-13 12:00:00+00:00',
    is_draft: true,
    rendered_excerpt: '',
    rendered_html: '<p>Test</p>',
    content: 'Test',
    labels: [],
  })
  mockFetchSocialAccounts.mockResolvedValue([
    {
      id: 1,
      platform: 'bluesky',
      account_name: 'alice.bsky.social',
      created_at: '2026-01-15T10:00:00Z',
    },
  ])

  const user = userEvent.setup()
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByText('Cross-post after saving:')).toBeInTheDocument()
  })

  // Toggle draft off to enable the bluesky checkbox
  const draftCheckbox = screen.getByRole('checkbox', { name: /draft/i })
  await user.click(draftCheckbox)

  // Check the platform checkbox (now enabled because draft is off)
  const blueskyCheckbox = screen.getByRole('checkbox', { name: /alice\.bsky\.social/i })
  await user.click(blueskyCheckbox)

  // Toggle draft back on — checkboxes get disabled but selection state is preserved
  await user.click(draftCheckbox)

  // Type a title and save
  await user.type(screen.getByLabelText(/Title/), 'Test')
  await user.click(screen.getByRole('button', { name: /save/i }))

  await waitFor(() => {
    expect(mockCreatePost).toHaveBeenCalledWith({
      title: 'Test',
      subtitle: null,
      body: '',
      labels: [],
      is_draft: true,
    })
  })

  // Cross-post dialog should NOT open for drafts
  expect(screen.queryByRole('heading', { name: 'Cross-post' })).not.toBeInTheDocument()
})
```

- [ ] **Step 5: Run tests to confirm failures**

```bash
just test-frontend 2>&1 | grep -A3 "FAIL\|✗\|×"
```

Expected: at least `creates new post on save`, `draft checkbox toggles isDraft`, and both cross-posting tests fail.

- [ ] **Step 6: Commit updated tests**

```bash
git add frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "test: update editor tests for draft-by-default new posts"
```

---

### Task 2: Implement draft-by-default

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx:46`

- [ ] **Step 1: Change `isDraft` initial state**

In `EditorPage.tsx`, find line 46:

```ts
const [isDraft, setIsDraft] = useState(false)
```

Change to:

```ts
const [isDraft, setIsDraft] = useState(isNew)
```

`isNew` is computed at line 38 and is stable by the time state initializers run. Existing posts have `isDraft` overwritten by the `fetchPostForEdit` load effect, so the `false` starting value for existing posts is irrelevant.

- [ ] **Step 2: Run tests — Task 1 failures should now pass, no new failures**

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|✓|✗"
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx
git commit -m "feat: default new posts to draft"
```

---

### Task 3: Write failing tests for the new switch toggle

The draft control will become a `<button role="switch">` instead of a checkbox. Write the new tests first, before touching the implementation, so the failures are explicit.

**Files:**
- Modify: `frontend/src/pages/__tests__/EditorPage.test.tsx`

- [ ] **Step 1: Add tests for the switch toggle**

Add the following tests inside the `describe('EditorPage', ...)` block, after the existing `draft checkbox toggles isDraft` test:

```ts
it('draft toggle is a switch with aria-checked reflecting isDraft', async () => {
  renderEditor('/editor/new')

  await waitFor(() => {
    const toggle = screen.getByRole('switch', { name: /draft/i })
    expect(toggle).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-checked', 'true')
  })
})

it('draft toggle shows "Not publicly visible" when draft is on', async () => {
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByRole('switch', { name: /draft/i })).toBeInTheDocument()
  })

  expect(screen.getByText('Not publicly visible')).toBeInTheDocument()
})

it('draft toggle shows "Publicly visible" and aria-checked=false when draft is off', async () => {
  const user = userEvent.setup()
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByRole('switch', { name: /draft/i })).toBeInTheDocument()
  })

  await user.click(screen.getByRole('switch', { name: /draft/i }))

  expect(screen.getByText('Publicly visible')).toBeInTheDocument()
  expect(screen.queryByText('Not publicly visible')).not.toBeInTheDocument()
  expect(screen.getByRole('switch', { name: /draft/i })).toHaveAttribute('aria-checked', 'false')
})
```

- [ ] **Step 2: Update all existing tests that query by `checkbox` role for the draft control**

There are 6 occurrences of `getByRole('checkbox', { name: /draft/i })` in the test file (lines 240, 320, 366, 729, 810, 1252). Change each to `getByRole('switch', { name: /draft/i })`.

Also update the `draft checkbox toggles isDraft` test (written in Task 1) to use `switch`:

```ts
it('draft toggle toggles isDraft', async () => {   // rename too
  const user = userEvent.setup()
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByRole('switch', { name: /draft/i })).toBeInTheDocument()
  })

  const toggle = screen.getByRole('switch', { name: /draft/i })
  expect(toggle).toHaveAttribute('aria-checked', 'true')  // starts as draft

  await user.click(toggle)
  expect(toggle).toHaveAttribute('aria-checked', 'false')
})
```

Replace all remaining `getByRole('checkbox', { name: /draft/i })` calls (the ones in the other tests) with `getByRole('switch', { name: /draft/i })`.

- [ ] **Step 3: Run tests to confirm failures**

```bash
just test-frontend 2>&1 | grep -A3 "FAIL\|✗\|×"
```

Expected: the four new switch-role tests fail (role not found), and the tests updated in step 2 fail (role mismatch).

- [ ] **Step 4: Commit updated tests**

```bash
git add frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "test: update editor tests for role=switch draft toggle"
```

---

### Task 4: Implement the switch toggle button

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx:433–444`

- [ ] **Step 1: Replace the checkbox with the switch button**

In `EditorPage.tsx`, find the block around lines 433–444 that currently reads:

```tsx
<label className="flex items-center gap-2 cursor-pointer">
  <input
    type="checkbox"
    checked={isDraft}
    onChange={(e) => setIsDraft(e.target.checked)}
    disabled={saving}
    className="rounded border-border text-accent focus:ring-accent/20"
  />
  <span className="text-sm text-ink">Draft</span>
</label>
```

Replace it with:

```tsx
<button
  type="button"
  role="switch"
  aria-checked={isDraft}
  aria-label="Draft"
  onClick={() => setIsDraft((d) => !d)}
  disabled={saving}
  className={`inline-flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-colors disabled:opacity-50 ${
    isDraft
      ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700'
      : 'bg-paper-warm border-border'
  }`}
>
  <div
    className={`relative w-8 h-[18px] rounded-full flex-shrink-0 transition-colors ${
      isDraft ? 'bg-amber-400 dark:bg-amber-500' : 'bg-border-dark'
    }`}
  >
    <div
      className={`absolute top-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm transition-transform ${
        isDraft ? 'translate-x-[14px]' : 'translate-x-0.5'
      }`}
    />
  </div>
  <div>
    <div
      className={`text-[10px] font-mono font-semibold uppercase tracking-widest leading-tight ${
        isDraft ? 'text-amber-800 dark:text-amber-300' : 'text-muted'
      }`}
    >
      DRAFT
    </div>
    <div
      className={`text-[11px] leading-tight mt-0.5 ${
        isDraft ? 'text-amber-700 dark:text-amber-400' : 'text-muted'
      }`}
    >
      {isDraft ? 'Not publicly visible' : 'Publicly visible'}
    </div>
  </div>
</button>
```

- [ ] **Step 2: Run tests**

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|✓|✗"
```

Expected: all tests pass.

- [ ] **Step 3: Run full check**

```bash
just check
```

Expected: all checks pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx
git commit -m "feat: replace draft checkbox with prominent amber switch toggle"
```
