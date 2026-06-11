# Subscribe Header Button Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the easily-missed muted mail icon in the site header with a discoverable outlined accent "Subscribe" pill, without adding any distraction to the reading experience.

**Architecture:** A single-component change in `frontend/src/components/layout/Header.tsx`. The existing `subscriptionsEnabled` gate and `/subscribe` link target are unchanged; only the rendered markup and styling of the subscribe control change. The control becomes an outlined pill (`Mail` icon + visible "Subscribe" label) that collapses to an icon-only outlined button below the `sm` breakpoint. Accessibility name and tooltip are preserved so existing tests stay valid.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4 (theme tokens in `frontend/src/index.css`), lucide-react icons, Vitest + Testing Library, Playwright MCP for live browser verification.

**Spec:** `docs/specs/2026-06-11-subscribe-header-button-design.md`

---

## Context for the implementer

- The subscribe control today is at `frontend/src/components/layout/Header.tsx:351-360`:

  ```tsx
  {subscriptionsEnabled && !searchOpen && (
    <Link
      to="/subscribe"
      className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
      aria-label="Subscribe"
      title="Subscribe to new posts"
    >
      <Mail size={18} />
    </Link>
  )}
  ```

  It lives inside the always-visible action cluster (`<div className="flex items-center gap-3 ...">`), so it appears in both the mobile top bar and on desktop. Leave its position in the cluster unchanged.

- `Mail` is already imported from `lucide-react` at the top of the file — no import change needed.
- Theme tokens (`accent`, `paper`, `muted`, etc.) are defined in `frontend/src/index.css` under `@theme`; `accent` is `#c44b2b` (light) / `#e8826a` (dark). Tailwind opacity modifiers like `bg-accent/10` and arbitrary values like `border-[1.5px]` are already used in this codebase, so both are safe.
- Tests live in `frontend/src/components/layout/__tests__/Header.test.tsx`. There is already a `describe('Subscribe link', ...)` block (around lines 901-919) with two tests: one asserting a `Subscribe` link to `/subscribe` exists when `subscriptions_enabled` is true, and one asserting it is absent when false. Both rely on the accessible name being exactly `"Subscribe"` — do NOT change the `aria-label`, or those tests break.
- Run the frontend test suite with `just test-frontend` (runs `vitest run --coverage`). There is no single-test just recipe; scan the output for the named test. Use `just check-frontend` for static checks + tests together. Do NOT call `vitest`/`npm` directly.
- Start the dev server with `just start` (backend :8000, frontend :5173) and stop it with `just stop` when done.

---

## Task 1: Failing test — visible "Subscribe" label

**Files:**
- Test: `frontend/src/components/layout/__tests__/Header.test.tsx` (add to the existing `describe('Subscribe link', ...)` block near line 918)

- [ ] **Step 1: Write the failing test**

Add this test inside the existing `describe('Subscribe link', () => { ... })` block, after the two existing tests (the `afterEach` that resets `siteConfig.subscriptions_enabled = false` already covers cleanup):

```tsx
it('shows the visible "Subscribe" label text when subscriptions are enabled', () => {
  siteConfig.subscriptions_enabled = true
  renderHeader()
  expect(screen.getByText('Subscribe')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test-frontend`
Expected: the new test `shows the visible "Subscribe" label text when subscriptions are enabled` FAILS with a "Unable to find an element with the text: Subscribe" error, because the current control renders only the `Mail` icon (the accessible name comes from `aria-label`, not visible text). The two pre-existing Subscribe-link tests should still PASS.

- [ ] **Step 3: Commit the failing test**

```bash
git add frontend/src/components/layout/__tests__/Header.test.tsx
git commit -m "test: assert header shows visible Subscribe label"
```

---

## Task 2: Implement the outlined pill

**Files:**
- Modify: `frontend/src/components/layout/Header.tsx:351-360`

- [ ] **Step 1: Replace the subscribe control markup**

Replace the existing block at `Header.tsx:351-360`:

```tsx
{subscriptionsEnabled && !searchOpen && (
  <Link
    to="/subscribe"
    className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
    aria-label="Subscribe"
    title="Subscribe to new posts"
  >
    <Mail size={18} />
  </Link>
)}
```

with the outlined pill:

```tsx
{subscriptionsEnabled && !searchOpen && (
  <Link
    to="/subscribe"
    className="flex items-center gap-1.5 rounded-full border-[1.5px] border-accent text-accent
             px-2 sm:px-3 py-1.5 text-sm font-medium transition-colors hover:bg-accent/10
             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
    aria-label="Subscribe"
    title="Subscribe to new posts"
  >
    <Mail size={16} aria-hidden="true" />
    <span className="hidden sm:inline">Subscribe</span>
  </Link>
)}
```

Notes for the implementer:
- `aria-label="Subscribe"` and `title="Subscribe to new posts"` are intentionally unchanged so the accessible name stays `"Subscribe"` across breakpoints (keeps the icon-only mobile view labelled and keeps existing tests green).
- The `<span className="hidden sm:inline">Subscribe</span>` is the visible label; it is hidden below the `sm` breakpoint, collapsing the pill to icon-only on narrow phones. In jsdom the span is still present in the DOM (Tailwind CSS is not applied), so `getByText('Subscribe')` finds it.
- `aria-hidden="true"` on `Mail` keeps the icon decorative.
- Do not move the block; it stays in the always-visible action cluster.

- [ ] **Step 2: Run the tests to verify they pass**

Run: `just test-frontend`
Expected: PASS. The new `shows the visible "Subscribe" label text ...` test now passes, and both pre-existing Subscribe-link tests (`renders a Subscribe link to /subscribe ...`, `does not render a Subscribe link ...`) still pass. No other Header tests regress.

- [ ] **Step 3: Run frontend static checks**

Run: `just check-frontend`
Expected: PASS (ESLint type-checked rules + tests). Fix any lint/type issues without disabling rules.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/Header.tsx
git commit -m "feat: make header subscribe button a discoverable outlined pill"
```

---

## Task 3: Live browser verification (Playwright MCP)

No code changes — this verifies the responsive and theme behavior that jsdom cannot.

**Prerequisite:** subscriptions must be enabled in the running dev site so the pill renders. If the local content's subscription settings have it disabled, enable it via the admin Subscriptions panel (log in, open `/admin`, Subscriptions tab) using a test Resend key, or temporarily point the site config at an enabled fixture. Verify the pill is visible before proceeding.

- [ ] **Step 1: Start the dev server**

Run: `just start`
Then confirm health: `just health`
Expected: backend (:8000) and frontend (:5173) report healthy.

- [ ] **Step 2: Verify desktop, light theme**

Using the Playwright MCP browser tools:
- Navigate to `http://localhost:5173/`.
- Resize the viewport to a desktop width (e.g. 1280×800).
- Confirm the header shows an outlined pill with the `Mail` icon AND the visible "Subscribe" text, in the accent color, sitting calmly beside the muted search/theme icons.
- Hover the pill and confirm the subtle accent-tinted background (`bg-accent/10`) appears.
- Tab to the pill and confirm a visible `focus-visible` accent ring.
- Click it and confirm navigation to `/subscribe`.

- [ ] **Step 3: Verify mobile, light theme**

- Resize the viewport to a narrow phone width (e.g. 375×800).
- Confirm the pill collapses to icon-only (outlined `Mail`, no "Subscribe" text) and still stands out against the muted icons, without crowding the title/hamburger.

- [ ] **Step 4: Verify dark theme**

- Toggle the theme to dark (theme button in the header).
- Repeat the desktop and mobile checks; confirm the pill uses the dark-mode accent (`#e8826a`) and remains legible against the dark paper background.

- [ ] **Step 5: Clean up**

- Delete any `*.png` screenshot files created during verification (per frontend CLAUDE.md).
- Run: `just stop` to stop the dev server.

There is nothing to commit in this task.

---

## Task 4: Update architecture docs

**Files:**
- Modify: `docs/arch/subscriptions.md` (the "Code Entry Points" list at the end)

- [ ] **Step 1: Add a header entry-point line**

In `docs/arch/subscriptions.md`, in the `## Code Entry Points` section, add a bullet noting the header subscribe control. Insert it directly before the `SubscribePage.tsx` bullet:

```markdown
- `frontend/src/components/layout/Header.tsx` renders the public subscribe entry point as an outlined accent "Subscribe" pill (icon + label, collapsing to icon-only below the `sm` breakpoint), shown when subscriptions are enabled.
```

- [ ] **Step 2: Commit**

```bash
git add docs/arch/subscriptions.md
git commit -m "docs: note header subscribe pill in subscriptions arch"
```

---

## Final verification

- [ ] **Step 1: Run the full gate**

Run: `just check`
Expected: PASS — static checks first, then all backend + frontend tests with coverage. Coverage stays above the 80% line / 70% branch targets.

- [ ] **Step 2: Confirm the branch is clean and ready**

Run: `git status`
Expected: clean working tree on `feat/subscribe-header-button`, with commits for the failing test, the implementation, the docs note, and the earlier spec commit.
