# Subscribe Header Button Redesign

**Date:** 2026-06-11
**Status:** Approved design

## Problem

The public subscription entry point is a single muted `Mail` icon in the site header
(`frontend/src/components/layout/Header.tsx`). It is visually identical to the search,
theme, and login icons beside it, so readers skim past it and never discover that the
blog offers email subscriptions. The opt-in form itself (`/subscribe`) is fine; the gap
is purely discoverability of the entry point.

## Goal

Make the subscribe action clearly discoverable without distracting from blog content.
Keep the change focused on the header entry point only.

## Non-Goals

- No end-of-post inline CTA card.
- No footer subscribe block.
- No changes to the `/subscribe` page, the subscription API, or the backend.
- No changes to the admin `SubscriptionsPanel`.

## Design

Replace the muted `Mail` icon at `Header.tsx:351-360` with an **outlined accent pill**:
a `Mail` icon plus a visible "Subscribe" label, accent border, accent text, transparent
fill. The control remains gated on `subscriptionsEnabled` and continues to link to
`/subscribe`.

### Visual specification

All values use existing Tailwind theme tokens, so dark mode adapts automatically (the
`accent` token resolves to `#c44b2b` in light, `#e8826a` in dark).

- **Shape:** rounded-full pill, roughly `px-3 py-1.5`.
- **Resting state:** `1.5px` accent border, accent text, transparent background; `Mail`
  icon at ~`15px` and label as `text-sm font-medium`.
- **Hover:** subtle accent wash background (`bg-accent/10`); border and text unchanged.
- **Focus:** `focus-visible` accent ring consistent with the header's other controls.
- **Hierarchy:** the pill stays *outlined*. The admin-only "Write" button remains the
  only solid-filled accent button, preserving a clean primary (Write) / secondary
  (Subscribe) split when an admin is logged in.

### Responsive behavior

- `sm` and up: full labeled pill (icon + "Subscribe").
- Below `sm` (narrow phones): collapse to an **accent-outlined icon-only button** — the
  `Mail` icon inside the same pill outline, no label. This still stands out against the
  muted search/theme icons (more discoverable than today's flat icon) without crowding
  the post title and hamburger menu.
- Placement stays in the current top-bar action cluster (after the theme toggle),
  visible on both mobile and desktop. The mobile hamburger menu is unchanged.

### Accessibility

- Keep `aria-label="Subscribe"` so the accessible name stays stable whether or not the
  text label is visible (it is hidden below `sm`). Keep the `title="Subscribe to new
  posts"` tooltip.
- Mark the `Mail` icon `aria-hidden` (the link's `aria-label` carries the name).
- The pill is a single focusable link; the `focus-visible` ring matches sibling controls.

## Testing

Following TDD (write failing tests first):

- Extend `frontend/src/components/layout/__tests__/Header.test.tsx`:
  1. Renders an accessible "Subscribe" link to `/subscribe` when subscriptions are
     enabled.
  2. Renders no subscribe control when subscriptions are disabled.
  3. The visible "Subscribe" label text is present in the DOM.
- The `< sm` icon-only collapse is CSS-breakpoint behavior and not unit-testable in
  jsdom; verify it live with Playwright at mobile and desktop widths, in both light and
  dark themes.

## Documentation

Update the frontend-surface line in `docs/arch/subscriptions.md` to note the header
subscribe CTA styling (outlined pill, responsive collapse).
