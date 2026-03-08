# Design: Move Filter Trigger to Header Toolbar

## Problem

The "Filters" button sits alone in the content area below the navigation tabs, visually disconnected from the search icon in the header toolbar. Both controls serve related purposes (narrowing down posts), but their separation makes the UI feel disjointed.

## Decision

Move the filter trigger to the header toolbar, adjacent to the search icon. Keep search and filter as separate controls — a unified bar adds complexity without proportional benefit for a blog's audience.

## Design

### Layout Change

Header toolbar icon order: `[search] [filter] [theme toggle] [login/logout]`

- **Filter icon**: Funnel icon, consistent with current design
- **Active filter badge**: Small count indicator when filters are active
- **Conditional rendering**: Filter icon only renders on the timeline page (`/`); hidden on all other pages (consistent with how Write/Admin buttons are already conditionally rendered)

### What Moves

- The toggle button (funnel icon + "Filters" text + chevron) moves from `FilterPanel` into `Header`
- The filter panel itself stays in the content area of `TimelinePage` (same position, contents, and animations)

### State Coordination

Panel open/close state must be shared between `Header` (trigger) and `TimelinePage` (panel). Use a small Zustand store (`useFilterPanelStore`) to avoid prop drilling through the layout tree.

### What Doesn't Change

- Filter panel contents (labels, date range, author)
- Filter panel expand/collapse animations
- Search behavior (inline input, navigates to `/search`)
- URL param sync for filter state
- Active filter chips display (shown when panel is collapsed)

## Components Affected

| Component | Change |
|-----------|--------|
| `Header.tsx` | Add filter icon with badge; conditional render on `/` route |
| `FilterPanel.tsx` | Remove built-in toggle button; open/close controlled externally via store |
| `TimelinePage.tsx` | Subscribe to store for panel state instead of managing locally |
| New: `useFilterPanelStore.ts` | Zustand store for panel open/close + active filter count |
