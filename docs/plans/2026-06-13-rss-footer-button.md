# RSS Footer Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inline RSS icon link to the existing site footer so readers can discover `/feed.xml` without cluttering the header.

**Architecture:** Single edit to `frontend/src/App.tsx` — add a `Rss` lucide icon as an `<a href="/feed.xml">` inline in the "Powered by AgBlogger" paragraph, separated by a `·` character. The `<link rel="alternate">` tag in `index.html` is already present; no backend changes required.

**Tech Stack:** React, lucide-react, Tailwind CSS, Vitest + Testing Library

---

### Task 1: Add RSS link to the footer

**Files:**
- Modify: `frontend/src/App.tsx:2-8` (imports), `frontend/src/App.tsx:76-98` (footer)
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

  Open `frontend/src/App.test.tsx` and add this test inside the existing `describe('App', ...)` block, after the last `describe('document.title', ...)` block:

  ```tsx
  it('renders RSS feed link in footer', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByRole('main')).toBeInTheDocument()
    })
    const rssLink = screen.getByRole('link', { name: 'RSS feed' })
    expect(rssLink).toHaveAttribute('href', '/feed.xml')
  })
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  just test-frontend
  ```

  Expected: FAIL — `Unable to find an accessible element with the role "link" and name "RSS feed"`

- [ ] **Step 3: Add the `Rss` import to `App.tsx`**

  At the top of `frontend/src/App.tsx`, add a new import line after the react-router-dom import block:

  ```tsx
  import { Rss } from "lucide-react";
  ```

- [ ] **Step 4: Add the RSS icon inline in the footer paragraph**

  In `frontend/src/App.tsx`, replace the footer `<p>` (currently lines 78–88):

  ```tsx
  <p className="text-xs text-muted text-center font-mono tracking-wide">
    Powered by{" "}
    <a
      href="https://agblogger.github.io"
      target="_blank"
      rel="noopener noreferrer"
      className="underline decoration-border hover:text-accent hover:decoration-accent transition-colors"
    >
      AgBlogger
    </a>
  </p>
  ```

  with:

  ```tsx
  <p className="text-xs text-muted text-center font-mono tracking-wide">
    Powered by{" "}
    <a
      href="https://agblogger.github.io"
      target="_blank"
      rel="noopener noreferrer"
      className="underline decoration-border hover:text-accent hover:decoration-accent transition-colors"
    >
      AgBlogger
    </a>
    {" "}
    <span className="text-muted/40" aria-hidden="true">·</span>
    {" "}
    <a
      href="/feed.xml"
      aria-label="RSS feed"
      title="RSS feed"
      className="inline-flex items-center text-muted hover:text-accent transition-colors"
    >
      <Rss size={14} aria-hidden="true" />
    </a>
  </p>
  ```

- [ ] **Step 5: Run tests to verify they pass**

  ```bash
  just test-frontend
  ```

  Expected: all tests pass including the new `renders RSS feed link in footer` test.

- [ ] **Step 6: Run full static + test gate**

  ```bash
  just check
  ```

  Expected: all checks pass (ruff, mypy, basedpyright, ESLint, full test suite).

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/App.tsx frontend/src/App.test.tsx
  git commit -m "feat: add RSS feed icon to site footer"
  ```
