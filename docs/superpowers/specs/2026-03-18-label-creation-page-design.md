# Label Creation Page

Add the ability to create new labels from the Labels page via a dedicated `/labels/new` page that shares form components with the existing `LabelSettingsPage`.

## Entry Point

A "+ New Label" button in the `LabelsPage` header bar, placed next to the search input and view toggle. Only visible to authenticated users (same auth gating as the existing per-label Settings link).

## Route

`/labels/new` → `LabelCreatePage` component. Requires authentication — redirects to `/login` if unauthenticated (same pattern as `LabelSettingsPage`).

## Create Page Layout

The page follows the same visual structure as `LabelSettingsPage`:

1. **Back link** → "Back to labels" linking to `/labels`
2. **Header** → Tag icon + "New Label" title + "Create Label" button (right-aligned)
3. **Label ID section** (create-only) → text input validated against `^[a-z0-9][a-z0-9-]*$`, max 100 chars. Helper text: "Lowercase letters, numbers, and hyphens. Cannot be changed after creation."
4. **Display Names section** (shared) → `LabelNamesEditor` component
5. **Parent Labels section** (shared) → `LabelParentsSelector` component
6. No delete/danger zone section

## Shared Components

Extract two sections from `LabelSettingsPage` into reusable components under `frontend/src/components/labels/`:

### `LabelNamesEditor`

Props:
- `names: string[]` — current list of display names
- `onNamesChange: (names: string[]) => void` — callback when names change
- `disabled: boolean` — disables all controls during async operations

Renders the display names tag list with remove buttons, plus the add-name input and button. Handles the add/remove logic internally but delegates state to the parent via `onNamesChange`.

### `LabelParentsSelector`

Props:
- `parents: string[]` — currently selected parent IDs
- `onParentsChange: (parents: string[]) => void` — callback when parents change
- `availableParents: LabelResponse[]` — labels eligible as parents (already filtered for cycle prevention)
- `disabled: boolean` — disables all controls during async operations
- `excludeHint?: string` — optional text explaining why some labels are excluded (e.g., "Labels that are descendants of #foo are excluded to prevent cycles.")

Renders the scrollable checkbox list of candidate parents. Handles toggle logic internally but delegates state to the parent via `onParentsChange`.

## Create Flow

1. User fills in label ID (required), optionally adds display names and selects parents
2. User clicks "Create Label"
3. Frontend calls `createLabel({ id, names, parents })` — the existing `POST /api/labels` endpoint
4. On success: navigate to `/labels/{newId}` (the label detail page)
5. On error:
   - 409 (conflict/duplicate ID) → "A label with this ID already exists."
   - 400 (validation) → "Invalid label ID. Use lowercase letters, numbers, and hyphens."
   - 401 (auth) → "Session expired. Please log in again."
   - Other → "Failed to create label. Please try again."

## Validation

- Client-side: the "Create Label" button is disabled when the label ID field is empty or doesn't match the ID regex
- Server-side: the backend validates the ID format and checks for duplicates

## Refactoring LabelSettingsPage

After extracting `LabelNamesEditor` and `LabelParentsSelector`, `LabelSettingsPage` imports them instead of inlining the markup. The page's own state management (`names`, `parents`, `savedNames`, `savedParents`, dirty tracking, save/delete handlers) stays in `LabelSettingsPage` — only the presentational sections move into shared components.

## Testing

- **LabelCreatePage tests**: render, validation (empty ID, invalid chars, valid ID), successful creation with navigation, error handling for each error code, auth redirect
- **LabelNamesEditor tests**: add name, remove name, duplicate prevention, disabled state
- **LabelParentsSelector tests**: toggle parent, disabled state, empty state
- **LabelSettingsPage tests**: existing tests continue to pass after refactor (no behavior change)
- **LabelsPage tests**: "+ New Label" button visible when authenticated, hidden when not
