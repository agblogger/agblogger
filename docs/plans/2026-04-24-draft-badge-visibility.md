# Draft Badge Visibility & Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make draft state more visible and consistent across the post list and post detail page.

**Architecture:** Two targeted CSS/JSX changes — PostCard gets its gray badge recolored amber; PostPage replaces a small amber pill with a prominent bordered banner that embeds the Publish button. No logic, API, or routing changes.

**Tech Stack:** React, TypeScript, Tailwind CSS (v4 with custom tokens in `frontend/src/index.css`), Vitest + Testing Library

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/components/posts/PostCard.tsx` | Change badge color classes (gray → amber) |
| `frontend/src/pages/PostPage.tsx` | Replace draft pill+row with amber banner |
| `frontend/src/pages/__tests__/PostPage.test.tsx` | Add assertion for banner description text |

---

### Task 1: Amber mono badge on PostCard

**Files:**
- Modify: `frontend/src/components/posts/PostCard.tsx:33`

The existing tests (`shows draft badge` / `hides draft badge` in `PostCard.test.tsx`) check text presence only — no test update needed. Just change the color classes.

- [ ] **Step 1: Update badge classes in PostCard**

In `frontend/src/components/posts/PostCard.tsx`, replace line 33:

```tsx
// before
<span className="text-[10px] font-mono font-semibold uppercase tracking-widest px-1.5 py-0.5 bg-muted/10 text-muted border border-muted/30 rounded shrink-0">
  DRAFT
</span>

// after
<span className="text-[10px] font-mono font-semibold uppercase tracking-widest px-1.5 py-0.5 bg-amber-100 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 border border-amber-300/50 dark:border-amber-700/50 rounded shrink-0">
  DRAFT
</span>
```

- [ ] **Step 2: Run PostCard tests**

```bash
just test-frontend -- --reporter=verbose PostCard
```

Expected: all tests pass (text-presence checks are unaffected by color class changes).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/posts/PostCard.tsx
git commit -m "style: recolor draft badge to amber on post list card"
```

---

### Task 2: Draft banner on PostPage

**Files:**
- Modify: `frontend/src/pages/__tests__/PostPage.test.tsx:415-433`
- Modify: `frontend/src/pages/PostPage.tsx:162-175`

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/__tests__/PostPage.test.tsx`, find the test `'shows draft badge and publish button for draft post when authenticated'` (around line 415). Add one assertion after the existing `expect(screen.getByText('Draft'))` line:

```ts
expect(screen.getByText('This post is not publicly visible yet')).toBeInTheDocument()
```

Full updated test body:

```ts
it('shows draft badge and publish button for draft post when authenticated', async () => {
  mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null }
  mockFetchPost.mockResolvedValue(draftPost)
  renderPostPage('/post/2026-03-08-draft')

  await waitFor(() => {
    expect(screen.getByText('My Draft')).toBeInTheDocument()
  })
  expect(screen.getByText('Draft')).toBeInTheDocument()
  expect(screen.getByText('This post is not publicly visible yet')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
  const shareButtons = screen.getAllByRole('button', { name: 'Share this post' })
  expect(shareButtons.length).toBeGreaterThanOrEqual(2)
  for (const button of shareButtons) {
    expect(button).toBeDisabled()
  }
  expect(screen.getByRole('button', { name: 'Share via email' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Copy link' })).toBeDisabled()
  expect(screen.getByText('Publish this draft to enable cross-posting.')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test-frontend -- --reporter=verbose PostPage
```

Expected: FAIL — `Unable to find an element with the text: This post is not publicly visible yet`

- [ ] **Step 3: Replace pill+row with banner in PostPage**

In `frontend/src/pages/PostPage.tsx`, replace lines 162–175:

```tsx
// before
{user && post.is_draft && (
  <div className="flex items-center justify-between mt-3">
    <span className="text-xs px-2 py-0.5 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full font-medium">
      Draft
    </span>
    <button
      onClick={() => void handlePublish()}
      disabled={publishing}
      className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent/90 rounded-lg transition-colors disabled:opacity-50"
    >
      {publishing ? 'Publishing...' : 'Publish'}
    </button>
  </div>
)}

// after
{user && post.is_draft && (
  <div className="mt-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg flex items-center justify-between gap-4">
    <div>
      <div className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-800 dark:text-amber-300">
        Draft
      </div>
      <div className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
        This post is not publicly visible yet
      </div>
    </div>
    <button
      onClick={() => void handlePublish()}
      disabled={publishing}
      className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent/90 rounded-lg transition-colors disabled:opacity-50 shrink-0"
    >
      {publishing ? 'Publishing...' : 'Publish'}
    </button>
  </div>
)}
```

- [ ] **Step 4: Run all frontend tests**

```bash
just test-frontend
```

Expected: all tests pass, including the new assertion.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "style: replace draft pill with prominent amber banner on post page"
```

---

### Task 3: Full gate check

- [ ] **Step 1: Run full check**

```bash
just check-frontend
```

Expected: all static checks and tests pass with no lint or type errors.
