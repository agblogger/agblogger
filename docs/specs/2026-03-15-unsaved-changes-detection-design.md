# Unsaved Changes Detection for Settings Pages

## Problem

Users can navigate away from the Label Settings page and Admin Panel sub-sections without being warned about unsaved changes. Edits to label parents, display names, site settings, account profile, password fields, and page order/content are silently lost.

## Scope

- Label Settings page (`LabelSettingsPage.tsx`)
- Admin Panel (`AdminPage.tsx`) with sub-sections: Site Settings, Pages, Account
- Social tab excluded — its operations are immediate API calls, not form-then-save

## Design

### Shared Hook: `useUnsavedChanges`

New file: `frontend/src/hooks/useUnsavedChanges.ts`

```typescript
function useUnsavedChanges(isDirty: boolean): { markSaved: () => void }
```

Responsibilities:
- Calls `useBlocker(isDirty)` to block react-router navigation. When blocked, shows `window.confirm('You have unsaved changes. Are you sure you want to leave?')`. Proceeds or resets based on response.
- Attaches `beforeunload` listener when dirty. Removes it when clean.
- `markSaved()` sets an internal ref that lets the next blocked navigation proceed without prompting. This is specifically needed because when a consumer calls `markSaved()` then triggers navigation in the same synchronous block, the `isDirty` boolean passed to `useBlocker` is still `true` (React hasn't re-rendered yet). The ref bypass handles this timing gap, matching the pattern in `useEditorAutoSave`.

Each consumer computes its own `isDirty` boolean and passes it in. The hook does not know what "dirty" means.

### LabelSettingsPage

**Dirty tracking:** Maintain `savedNames` and `savedParents` state that captures the last-saved (or initially-loaded) values. `isDirty` is true when either the current `names` or `parents` arrays differ from their saved counterparts. Comparison is order-sensitive (the arrays are sent as-is to the API, so order is meaningful).

**Hook usage:** Call `useUnsavedChanges(isDirty)`. Call `markSaved()` inside `handleSave` after a successful API response and state update.

**Save button relocation:** Move the Save button from its current position (between Parents section and Danger Zone) to a top bar, right after the page heading:

```
Back to #swe
Label Settings: #swe          [Save Changes]
```

The button is disabled when `busy` or `!isDirty`.

### AdminPage Dirty State Aggregation

Admin sub-sections are child components rendered conditionally by tab. Only the active tab is mounted. The hook lives in AdminPage, with children reporting dirty state upward.

**Two separate guard mechanisms (non-overlapping):**
- `useUnsavedChanges(anyDirty)` guards react-router navigation (leaving `/admin` entirely) and browser close/refresh.
- Tab switch `onClick` handler guards in-page tab switching (purely local state, not a route change, so `useBlocker` does not fire).

**New callback prop:** Each section receives `onDirtyChange: (dirty: boolean) => void`. AdminPage provides stable callbacks (direct state setters or `useCallback`) so cleanup effects fire correctly.

**Per-section dirty computation:**

- **SiteSettingsSection**: dirty when `siteSettings` differs from `initialSettings` (comparing title, description, timezone).
- **AccountSection**: dirty when `profileChanged` is true OR any password field is non-empty. On successful password change with session revocation, the section must call `onDirtyChange(false)` before the `logout()` call triggers navigation, preventing a spurious blocker dialog.
- **PagesSection**: dirty when page order differs from initial page order (computed by comparing page ID arrays, not a one-way flag) OR when the expanded page's `editTitle`/`editContent` differs from the page's saved values OR when the Add Page form is visible and has any input (`addPageDirty = showAddForm && (newPageId !== '' || newPageTitle !== '')`). Page edit dirty is tracked only while a page row is expanded (the current `handleExpandPage` resets edit state from server values on re-expand, so edits don't survive collapse/re-expand). The "Save Order" button is shown only when the order actually differs from initial — if the user reorders pages back to the original order, the button disappears.
- **SocialAccountsPanel**: no dirty tracking.

**AdminPage aggregation:** Tracks `siteDirty`, `pagesDirty`, `accountDirty` via the callbacks. Computes `anyDirty = siteDirty || pagesDirty || accountDirty` and passes it to `useUnsavedChanges(anyDirty)`.

**Tab switching guard:** Before switching tabs, if the outgoing section is dirty, show `window.confirm(...)`. If the user cancels, don't switch tabs.

**Cleanup on unmount:** When a section unmounts (user confirms tab switch), it reports `false` via a cleanup effect so stale dirty flags don't linger.

### Confirm Dialog

All unsaved changes prompts use `window.confirm('You have unsaved changes. Are you sure you want to leave?')` — the same pattern used by the editor's `useEditorAutoSave` hook.

## Files Changed

| File | Change |
|---|---|
| `frontend/src/hooks/useUnsavedChanges.ts` | New hook |
| `frontend/src/hooks/__tests__/useUnsavedChanges.test.ts` | New test file |
| `frontend/src/pages/LabelSettingsPage.tsx` | Dirty tracking, hook usage, Save button moved to top |
| `frontend/src/pages/__tests__/LabelSettingsPage.test.tsx` | Dirty state and Save placement tests |
| `frontend/src/pages/AdminPage.tsx` | Dirty aggregation, hook usage, tab switch guard |
| `frontend/src/components/admin/SiteSettingsSection.tsx` | `onDirtyChange` prop, dirty computation |
| `frontend/src/components/admin/AccountSection.tsx` | `onDirtyChange` prop, dirty computation, explicit `onDirtyChange(false)` before logout |
| `frontend/src/components/admin/PagesSection.tsx` | `onDirtyChange` prop, computed order dirty, expanded page edit dirty |
| `frontend/src/pages/__tests__/AdminPage.test.tsx` | Dirty aggregation and tab switch guard tests |

## Testing

**`useUnsavedChanges` hook tests:**
- When `isDirty` is false, blocker does not activate
- When `isDirty` is true, blocker activates and shows confirm dialog
- Confirm accept allows navigation
- Confirm cancel resets blocker
- `beforeunload` listener attached when dirty, removed when clean
- `markSaved()` allows the next navigation without prompting

**LabelSettingsPage tests:**
- Toggling parents or editing names makes the page dirty
- Save button is disabled when not dirty
- Successful save resets dirty state
- Reverting changes to original values resets dirty state

**AdminPage / sub-section tests:**
- Each section reports dirty via `onDirtyChange` when form state diverges from initial
- Tab switch with unsaved changes shows confirm dialog
- Tab switch without changes proceeds immediately
- PagesSection: reordering pages then reordering back results in not-dirty and "Save Order" hidden

## Non-Goals

- No localStorage draft persistence for settings pages (unlike the editor)
- No auto-save
- No custom styled modal — uses native browser confirm dialog
- No backend changes
- Add Page form in PagesSection is included in dirty tracking — a user who has started filling out the form should be warned before losing that data
