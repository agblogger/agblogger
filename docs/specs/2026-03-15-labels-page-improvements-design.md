# Labels Page Improvements

## Overview

Improve the label list view with three enhancements: search filtering, visible children in label cards, and clickable parent/child navigation.

## Changes

### 1. Search Filter in List View

Add a search input to the list view header, positioned between the page title and the view toggle — matching the graph view's layout.

- Reuse `matchesLabelSearch()` and `filterLabelsBySearch()` from `components/labels/searchUtils.ts`
- Case-insensitive substring matching against label ID and display names
- Non-matching labels are hidden entirely from the grid (not dimmed)
- Empty search shows all labels
- When the search matches zero labels, show a message: "No labels match your search."
- Search input positioned in the right-aligned header group alongside the view toggle (matching the graph view's `ml-auto` placement), with placeholder text "Filter labels..."

### 2. Children Display (Prominent)

When a label has children (immediate descendants), display them as a row of clickable `LabelChip` components directly below the label name and aliases.

- Children appear above the parents text in the card layout (see Section 4 for exact ordering)
- Each child chip is a link to `/labels/{childId}` (the label's posts page)
- Reuse the existing `LabelChip` component (already renders as a clickable `#id` badge)
- Chips wrap naturally if there are many children

### 3. Parents Display (Subtle)

Replace the current parent tags with subtle inline text below the children row.

- Format: `in #parent1, #parent2` — where each parent ID is a clickable link
- Parent links navigate to `/labels/{parentId}` (the parent label's posts page, same destination as clicking a card)
- Styled as subtle underlined text links (not full chips) to maintain visual hierarchy: children > parents
- The "in" prefix replaces the current "Parent:"/"Parents:" label for a more natural reading

### 4. Card Layout (Top to Bottom)

1. Label ID (`#name`) + post count badge
2. Display names/aliases (if any)
3. Children chips (if any) — clickable `LabelChip` components
4. Parents text (if any) — subtle "in #parent" links
5. Settings link (authenticated users only)

### 5. Nested Link Handling

The card is wrapped in a full-card `<Link>` to the label's posts page. The card's inner content `<div>` has `pointer-events-none` to let clicks fall through to the card link. Interactive elements (children chips, parent links, settings link) must be placed in a wrapper with `pointer-events-auto relative z-10` to break out of the `pointer-events-none` container — the same pattern already used for the settings link. `LabelChip` instances need this wrapper around them since `LabelChip` itself does not set `pointer-events-auto`.

## Existing Code to Reuse

- `LabelChip` (`components/labels/LabelChip.tsx`) — clickable label badge
- `matchesLabelSearch`, `filterLabelsBySearch` (`components/labels/searchUtils.ts`) — search utilities
- `LabelResponse.children` field — already available in the API response

## Files to Modify

- `frontend/src/pages/LabelsPage.tsx` — add search input, update card layout with children and clickable parents
