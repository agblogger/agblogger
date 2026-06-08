# Draft Toggle — Editor Default & Prominent UI

**Date:** 2026-06-08

## Overview

Two related improvements to draft handling in the post editor:

1. New posts default to draft status.
2. The draft toggle is redesigned to match the amber "DRAFT" badge style used on post cards and the post page.

## Part 1 — Default to draft on new posts

### Change

In `frontend/src/pages/EditorPage.tsx`, the `isDraft` state initializer changes from `false` to `isNew`:

```ts
// before
const [isDraft, setIsDraft] = useState(false)

// after
const [isDraft, setIsDraft] = useState(isNew)
```

`isNew` is a boolean derived from the route params before state initialization runs, so this correctly sets new posts to `true` and leaves existing posts at `false` (their value is overwritten by the load effect from the API response).

The auto-save draft restore path (`handleRestore`) already sets `isDraft` from the saved draft data, so restored drafts are unaffected.

## Part 2 — Prominent draft toggle

### Current state

The draft control is a plain `<input type="checkbox">` with a `<span>Draft</span>` label, sitting in a small flex row alongside the Author field. It is easy to miss.

### New design

Replace the checkbox+label with a styled toggle pill. The pill and the Author field remain in the same flex row, but Author sits outside the pill.

**Draft on (amber state):**
- Pill background: `bg-amber-50 dark:bg-amber-900/20`
- Pill border: `border-amber-300 dark:border-amber-700`
- Toggle thumb: amber (`bg-amber-400`)
- Label: `DRAFT` — `font-mono font-semibold uppercase tracking-widest text-[10px] text-amber-800 dark:text-amber-300`
- Sub-label: "Not publicly visible" — `text-[11px] text-amber-700 dark:text-amber-400`

**Draft off (muted state):**
- Pill background: `bg-paper-warm`
- Pill border: `border-border`
- Toggle thumb: muted (`bg-border-dark`)
- Label: `DRAFT` — same sizing, `text-muted`
- Sub-label: "Publicly visible" — `text-[11px] text-muted`

### Accessibility

The toggle is implemented as `<button role="switch" aria-checked={isDraft}>` so it is keyboard-operable (Space/Enter to toggle) and exposes the correct ARIA state.

### Scope

Only `EditorPage.tsx` changes. No backend changes, no API changes, no changes to PostCard or PostPage draft display.

## Testing

- Unit: `EditorPage` tests verify `isDraft` defaults to `true` for new posts and `false` for loaded existing posts.
- Unit: toggle button renders with correct ARIA state and amber/muted styling for each state.
- Unit: toggling the button flips `isDraft` state.
- Existing auto-save restore tests continue to pass (`isDraft` round-trips through `DraftData`).
