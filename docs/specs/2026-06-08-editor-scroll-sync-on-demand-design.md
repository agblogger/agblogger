# Editor Scroll Sync — On-Demand Redesign

## Goal

Replace the continuous automatic scroll synchronization between the editor and preview panes with explicit on-demand sync triggered by two directional buttons, matching the Overleaf editor pattern.

## Background

The initial implementation used scroll event listeners for bidirectional auto-sync. In practice this produced ghostly scrolling artifacts — both panes would drift without user involvement — due to re-entrancy edge cases and the complexity of keeping two continuously scrolling panes in sync. The position-mapping infrastructure (backend sentinels + mirror div + piecewise-linear interpolation) works correctly; only the triggering mechanism needs to change.

## Architecture

### Hook API

`useScrollSync` exposes two imperative sync functions instead of event handlers and a toggle:

```typescript
// Removed
{ syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }

// New
{ syncEditorToPreview: () => void, syncPreviewToEditor: () => void }
```

Internally:
- `syncEnabled`, `syncEnabledRef`, `syncingRef` (re-entrancy guard) — **removed**
- `onEditorScroll`, `onPreviewScroll` callbacks — **removed**
- `getOrBuildMap`, ResizeObserver, MutationObserver invalidation — **kept** (map still needs to stay accurate after resize or image load)
- Each sync function: calls `getOrBuildMap()`, computes target `scrollTop` via existing interpolation helpers, sets it directly with no animation

### Layout

The editor grid changes from 2-column to 3-column with a narrow explicit gutter:

```
grid-cols-1                       (mobile — gutter hidden)
grid-cols-[1fr_2.5rem_1fr]        (desktop lg+)
```

The center gutter column is `hidden lg:flex flex-col items-center justify-center gap-2` and contains two icon buttons:

| Button | Icon | Direction | `title` |
|--------|------|-----------|---------|
| Top | `ChevronRight` | editor → preview | `"Go to editor position in preview"` |
| Bottom | `ChevronLeft` | preview → editor | `"Go to preview position in editor"` |

Both buttons use `aria-label` matching their `title`. Style follows the existing MarkdownToolbar button pattern (`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors`).

The "⇄ Sync" toggle row above the grid is **removed**. `onScroll` props are **removed** from the textarea and preview div.

## Component Changes

| File | Change |
|------|--------|
| `frontend/src/hooks/useScrollSync.ts` | Remove continuous sync; expose `syncEditorToPreview`/`syncPreviewToEditor` |
| `frontend/src/pages/EditorPage.tsx` | Replace 2-col grid with 3-col; add gutter buttons; remove toggle row and `onScroll` props |
| `frontend/src/hooks/__tests__/useScrollSync.test.ts` | Remove toggle/re-entrancy tests; add tests for the two new sync functions |

Backend files (`backend/pandoc/sentinel.py`, `backend/api/render.py`) are unchanged — sentinel injection is unaffected.

## Testing

- `syncEditorToPreview`: sets `preview.scrollTop` to the interpolated position given `textarea.scrollTop`
- `syncPreviewToEditor`: sets `textarea.scrollTop` to the interpolated position given `preview.scrollTop`
- Null-ref no-ops: calling either function with null refs does not throw
- Pure interpolation helpers: no changes to existing tests
