# Label Detail Page: Display Clickable Parents and Children

**Date:** 2026-03-15

## Problem

The label detail page (`/labels/:labelId`, `LabelPostsPage.tsx`) shows the label ID, display names, and posts — but no hierarchy information. Parents and children are only visible on the label cards in the list view (`LabelsPage.tsx`). Users navigating to a label's detail page lose context about where it sits in the label DAG.

## Design

### Placement

Add two optional hierarchy sections between the label name/aliases block and the post list, in this order:

1. **Children** (rendered only when `label.children.length > 0`)
2. **Parents** (rendered only when `label.parents.length > 0`)

Children come first and are more visually prominent because they are more important to the user.

### Children Section

- Small heading: "Children" — styled `text-sm font-medium text-muted`
- Below the heading, a flex-wrap row of `LabelChip` components (reusing the existing component from `@/components/labels/LabelChip`)
- Spacing: `gap-2` between chips (slightly more generous than the `gap-1.5` used on label cards)

### Parents Section

- Small heading: "Parents" — styled `text-sm font-medium text-muted`
- Below the heading, inline `Link` elements styled as `#parentId` with `text-muted hover:text-ink underline decoration-border hover:decoration-ink transition-colors`
- No "in" prefix (the heading provides context)
- Comma-separated when multiple parents exist

### Spacing

- `mt-4` between the aliases line (or header if no aliases) and the first hierarchy section
- `mt-3` between children and parents sections when both are present
- `mb-8` on the last element before the post list (shifts from aliases to the last hierarchy section when hierarchy exists)

### Data

`LabelResponse` already includes `parents: string[]` and `children: string[]`. The page already fetches label data via `fetchLabel()`. No backend or API changes are needed.

### Testing

Add test cases to `LabelPostsPage.test.tsx`:

- Label with children renders clickable `LabelChip` components linking to `/labels/{childId}`
- Label with parents renders clickable links to `/labels/{parentId}`
- Label with neither parents nor children renders no hierarchy sections
