# Unsaved Changes Detection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn users about unsaved changes when navigating away from Label Settings and Admin Panel settings pages.

**Architecture:** A shared `useUnsavedChanges` hook handles `useBlocker` + `beforeunload`. Each consumer computes its own `isDirty` boolean. Admin sub-sections report dirty state upward via callbacks; AdminPage aggregates and guards tab switches separately.

**Tech Stack:** React, react-router-dom v6 (`useBlocker`), Vitest, Testing Library

**Spec:** `docs/specs/2026-03-15-unsaved-changes-detection-design.md`

---

## File Structure

| File | Role |
|---|---|
| `frontend/src/hooks/useUnsavedChanges.ts` | New shared hook — `useBlocker` + `beforeunload` + `markSaved()` |
| `frontend/src/hooks/__tests__/useUnsavedChanges.test.ts` | Hook unit tests |
| `frontend/src/pages/LabelSettingsPage.tsx` | Add dirty tracking, wire hook, relocate Save button |
| `frontend/src/pages/__tests__/LabelSettingsPage.test.tsx` | Extend with dirty state + Save placement tests |
| `frontend/src/components/admin/SiteSettingsSection.tsx` | Add `onDirtyChange` prop, compute dirty |
| `frontend/src/components/admin/AccountSection.tsx` | Add `onDirtyChange` prop, compute dirty |
| `frontend/src/components/admin/PagesSection.tsx` | Add `onDirtyChange` prop, computed `orderDirty`, page edit dirty |
| `frontend/src/pages/AdminPage.tsx` | Aggregate dirty state, wire hook, guard tab switches |
| `frontend/src/pages/__tests__/AdminPage.test.tsx` | Switch to `createMemoryRouter`, add dirty/tab-switch tests |

---

## Chunk 1: Shared Hook + LabelSettingsPage

### Task 1: Create `useUnsavedChanges` hook

**Files:**
- Create: `frontend/src/hooks/useUnsavedChanges.ts`
- Create: `frontend/src/hooks/__tests__/useUnsavedChanges.test.ts`

- [ ] **Step 1: Write failing tests for the hook**

Create `frontend/src/hooks/__tests__/useUnsavedChanges.test.ts`:

```typescript
import { renderHook, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { createElement } from 'react'
import { createMemoryRouter, RouterProvider, Link, useLocation } from 'react-router-dom'

import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'

/** Wrapper for renderHook — single-route data router so useBlocker works. */
function createWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const router = createMemoryRouter(
      [{ path: '/', element: children }],
      { initialEntries: ['/'] },
    )
    return createElement(RouterProvider, { router })
  }
}

/** Component wrapper for testing blocker behavior via user interaction. */
function TestHost({ isDirty }: { isDirty: boolean }) {
  useUnsavedChanges(isDirty)
  const location = useLocation()
  return (
    <>
      <span data-testid="location">{location.pathname}</span>
      <Link to="/other">Leave</Link>
    </>
  )
}

function renderWithHost(isDirty: boolean) {
  const router = createMemoryRouter(
    [
      { path: '/', element: createElement(TestHost, { isDirty }) },
      { path: '/other', element: createElement('div', null, 'Other page') },
    ],
    { initialEntries: ['/'] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('useUnsavedChanges', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  describe('beforeunload', () => {
    it('registers beforeunload when dirty', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')

      renderHook(() => useUnsavedChanges(true), { wrapper: createWrapper() })

      expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    })

    it('does not register beforeunload when not dirty', () => {
      const addSpy = vi.spyOn(window, 'addEventListener')

      renderHook(() => useUnsavedChanges(false), { wrapper: createWrapper() })

      const beforeunloadCalls = addSpy.mock.calls.filter(([event]) => event === 'beforeunload')
      expect(beforeunloadCalls).toHaveLength(0)
    })

    it('unregisters beforeunload when dirty becomes false', () => {
      const removeSpy = vi.spyOn(window, 'removeEventListener')

      const { rerender } = renderHook(
        ({ dirty }) => useUnsavedChanges(dirty),
        { wrapper: createWrapper(), initialProps: { dirty: true } },
      )

      rerender({ dirty: false })

      expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    })
  })

  describe('navigation blocker', () => {
    it('shows confirm dialog when navigating while dirty', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalledWith(
        'You have unsaved changes. Are you sure you want to leave?',
      )
      // Navigation should be blocked
      expect(screen.getByTestId('location')).toHaveTextContent('/')
    })

    it('allows navigation when user confirms', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('Other page')).toBeInTheDocument()
      })
    })

    it('blocks navigation when user cancels', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()
      renderWithHost(true)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).toHaveBeenCalled()
      expect(screen.getByTestId('location')).toHaveTextContent('/')
    })

    it('does not show confirm when not dirty', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm')
      const user = userEvent.setup()
      renderWithHost(false)

      await user.click(screen.getByText('Leave'))

      expect(confirmSpy).not.toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('Other page')).toBeInTheDocument()
      })
    })
  })

  describe('markSaved', () => {
    it('returns a markSaved function', () => {
      const { result } = renderHook(() => useUnsavedChanges(false), {
        wrapper: createWrapper(),
      })

      expect(result.current.markSaved).toBeInstanceOf(Function)
    })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend -- --run frontend/src/hooks/__tests__/useUnsavedChanges.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useUnsavedChanges.ts`:

```typescript
import { useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

export function useUnsavedChanges(isDirty: boolean): { markSaved: () => void } {
  const navigationAllowedRef = useRef(false)

  useEffect(() => {
    if (!isDirty) return

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  const blocker = useBlocker(isDirty)

  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (navigationAllowedRef.current) {
        navigationAllowedRef.current = false
        blocker.proceed()
        return
      }
      const leave = window.confirm('You have unsaved changes. Are you sure you want to leave?')
      if (leave) {
        blocker.proceed()
      } else {
        blocker.reset()
      }
    }
  }, [blocker])

  return {
    markSaved: () => {
      navigationAllowedRef.current = true
    },
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend -- --run frontend/src/hooks/__tests__/useUnsavedChanges.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useUnsavedChanges.ts frontend/src/hooks/__tests__/useUnsavedChanges.test.ts
git commit -m "feat: add useUnsavedChanges hook"
```

---

### Task 2: Wire up LabelSettingsPage

**Files:**
- Modify: `frontend/src/pages/LabelSettingsPage.tsx`
- Modify: `frontend/src/pages/__tests__/LabelSettingsPage.test.tsx`

**Reference:** Current `LabelSettingsPage.tsx` has `names`/`parents` state (lines 24-25) initialized from fetched label (lines 48-49). Save button is at lines 273-282 between the Parents section and Danger Zone.

- [ ] **Step 1: Write failing tests for dirty tracking and Save button placement**

Add to the existing `LabelSettingsPage.test.tsx`, inside the existing `describe('LabelSettingsPage', ...)` block:

```typescript
it('save button is disabled when no changes have been made', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('software engineering')).toBeInTheDocument()
  })

  expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
})

it('save button is enabled after toggling a parent', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('#cs')).toBeInTheDocument()
  })

  await user.click(screen.getByRole('checkbox', { name: /#cs/i }))
  expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()
})

it('save button is enabled after adding a name', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('software engineering')).toBeInTheDocument()
  })

  await user.type(screen.getByPlaceholderText('Add a display name...'), 'coding')
  await user.click(screen.getByRole('button', { name: 'Add' }))
  expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()
})

it('save button becomes disabled after successful save', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  mockUpdateLabel.mockResolvedValue({ ...testLabel, parents: [] })
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('#cs')).toBeInTheDocument()
  })

  // Make dirty
  await user.click(screen.getByRole('checkbox', { name: /#cs/i }))
  expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()

  // Save
  await user.click(screen.getByRole('button', { name: /save changes/i }))

  await waitFor(() => {
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })
})

it('reverting changes back to original makes save button disabled', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('#cs')).toBeInTheDocument()
  })

  const csCheckbox = screen.getByRole('checkbox', { name: /#cs/i })

  // Uncheck cs → dirty
  await user.click(csCheckbox)
  expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()

  // Re-check cs → back to original
  await user.click(csCheckbox)
  expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
})

it('save button appears near the page heading', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('software engineering')).toBeInTheDocument()
  })

  // The Save button should be in the same header area as the page title
  const heading = screen.getByRole('heading', { level: 1 })
  const saveButton = screen.getByRole('button', { name: /save changes/i })

  // Both should share a common parent container (the header row)
  expect(heading.closest('.flex')?.contains(saveButton)).toBe(true)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend -- --run frontend/src/pages/__tests__/LabelSettingsPage.test.tsx`
Expected: FAIL — Save button is never disabled (no dirty tracking yet)

- [ ] **Step 3: Implement dirty tracking, hook wiring, and Save button relocation**

In `LabelSettingsPage.tsx`:

1. Add import:
```typescript
import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'
```

2. Add `useMemo` to the existing `import { useEffect, useState, useMemo } from 'react'` (already present).

3. After the existing `parents` state (line 25), add saved-state tracking:
```typescript
const [savedNames, setSavedNames] = useState<string[]>([])
const [savedParents, setSavedParents] = useState<string[]>([])
```

4. In the fetch effect (lines 44-63), after setting `names` and `parents`, also set the saved state:
```typescript
setNames([...l.names])
setParents([...l.parents])
setSavedNames([...l.names])
setSavedParents([...l.parents])
```

5. Add dirty computation after the state declarations:
```typescript
const isDirty = useMemo(() => {
  if (names.length !== savedNames.length) return true
  if (parents.length !== savedParents.length) return true
  for (let i = 0; i < names.length; i++) {
    if (names[i] !== savedNames[i]) return true
  }
  for (let i = 0; i < parents.length; i++) {
    if (parents[i] !== savedParents[i]) return true
  }
  return false
}, [names, savedNames, parents, savedParents])
```

6. Call the hook (destructure `markSaved`):
```typescript
const { markSaved } = useUnsavedChanges(isDirty)
```

7. In `handleSave`, after the successful API response updates state (lines 104-106), also update saved state and call `markSaved()`:
```typescript
const updated = await updateLabel(labelId, { names, parents })
setLabel(updated)
setNames([...updated.names])
setParents([...updated.parents])
setSavedNames([...updated.names])
setSavedParents([...updated.parents])
markSaved()
```

8. Move the Save button from its current location (lines 273-282) into the heading row. Replace the heading `div` (lines 175-178) with:
```tsx
<div className="flex items-center gap-3 mb-8">
  <Settings size={20} className="text-accent" />
  <h1 className="font-display text-3xl text-ink">Label Settings: #{labelId}</h1>
  <div className="ml-auto">
    <button
      onClick={() => void handleSave()}
      disabled={busy || !isDirty}
      className="px-6 py-2.5 text-sm font-medium bg-accent text-white rounded-lg
               hover:bg-accent-light disabled:opacity-50 transition-colors"
    >
      {saving ? 'Saving...' : 'Save Changes'}
    </button>
  </div>
</div>
```

9. Remove the old Save button section (the `<div className="mb-10">` block that previously held the Save button).

- [ ] **Step 4: Update existing tests broken by the new `disabled={!isDirty}` condition**

The existing "saves label changes" and "allows saving with no display names" tests click Save without making changes first. Now that Save is disabled when not dirty, these tests need to make a change before clicking Save.

In `LabelSettingsPage.test.tsx`, update the "saves label changes" test to first make a change:

```typescript
it('saves label changes', async () => {
  mockFetchLabel.mockResolvedValue(testLabel)
  mockFetchLabels.mockResolvedValue(allLabels)
  mockUpdateLabel.mockResolvedValue(testLabel)
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByText('software engineering')).toBeInTheDocument()
  })

  // Make a change to enable Save (add then remove a name to trigger dirty)
  await user.type(screen.getByPlaceholderText('Add a display name...'), 'temp')
  await user.click(screen.getByRole('button', { name: 'Add' }))
  await user.click(screen.getByLabelText('Remove name "temp"'))

  // Now add a real change: toggle math parent
  const mathCheckbox = screen.getByRole('checkbox', { name: /#math/i })
  await user.click(mathCheckbox)

  await user.click(screen.getByRole('button', { name: /save changes/i }))

  await waitFor(() => {
    expect(mockUpdateLabel).toHaveBeenCalledWith('swe', {
      names: ['software engineering', 'programming'],
      parents: ['cs', 'math'],
    })
  })
})
```

Update the "allows saving with no display names" test similarly:

```typescript
it('allows saving with no display names', async () => {
  mockFetchLabel.mockResolvedValue({ ...testLabel, names: [] })
  mockFetchLabels.mockResolvedValue(allLabels)
  mockUpdateLabel.mockResolvedValue({ ...testLabel, names: [], parents: ['cs', 'math'] })
  const user = userEvent.setup()
  renderSettings()

  await waitFor(() => {
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
  })

  // Make a change to enable Save — toggle math parent on
  const mathCheckbox = screen.getByRole('checkbox', { name: /#math/i })
  await user.click(mathCheckbox)

  await user.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => {
    expect(mockUpdateLabel).toHaveBeenCalledWith('swe', { names: [], parents: ['cs', 'math'] })
  })
  expect(screen.queryByText('At least one display name is required.')).not.toBeInTheDocument()
})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-frontend -- --run frontend/src/pages/__tests__/LabelSettingsPage.test.tsx`
Expected: PASS

- [ ] **Step 6: Run full frontend checks**

Run: `just check-frontend`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/LabelSettingsPage.tsx frontend/src/pages/__tests__/LabelSettingsPage.test.tsx
git commit -m "feat: add unsaved changes detection to LabelSettingsPage"
```

---

## Chunk 2: Admin Sub-Sections + AdminPage

### Task 3: Add `onDirtyChange` to SiteSettingsSection

**Files:**
- Modify: `frontend/src/components/admin/SiteSettingsSection.tsx`

- [ ] **Step 1: Add `onDirtyChange` prop and dirty computation**

In `SiteSettingsSection.tsx`:

1. Add `onDirtyChange` to the props interface:
```typescript
interface SiteSettingsSectionProps {
  initialSettings: AdminSiteSettings
  busy: boolean
  onSaving: (saving: boolean) => void
  onSavedSettings: (settings: AdminSiteSettings) => void
  onDirtyChange: (dirty: boolean) => void
}
```

2. Destructure the new prop:
```typescript
export default function SiteSettingsSection({
  initialSettings,
  busy,
  onSaving,
  onSavedSettings,
  onDirtyChange,
}: SiteSettingsSectionProps) {
```

3. After the existing `useEffect` for `onSaving` (line 40), add dirty computation and reporting:
```typescript
const isDirty =
  siteSettings.title !== normalizeSiteSettings(initialSettings).title ||
  siteSettings.description !== normalizeSiteSettings(initialSettings).description ||
  siteSettings.timezone !== normalizeSiteSettings(initialSettings).timezone

useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])
useEffect(() => { return () => { onDirtyChange(false) } }, [onDirtyChange])
```

Note: memoize the normalized initial settings to avoid recomputing on every render. Use `useMemo`:

```typescript
const normalizedInitial = useMemo(() => normalizeSiteSettings(initialSettings), [initialSettings])

const isDirty =
  siteSettings.title !== normalizedInitial.title ||
  siteSettings.description !== normalizedInitial.description ||
  siteSettings.timezone !== normalizedInitial.timezone
```

Add `useMemo` to the import from `react`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/admin/SiteSettingsSection.tsx
git commit -m "feat: add onDirtyChange to SiteSettingsSection"
```

---

### Task 4: Add `onDirtyChange` to AccountSection

**Files:**
- Modify: `frontend/src/components/admin/AccountSection.tsx`

- [ ] **Step 1: Add `onDirtyChange` prop and dirty computation**

In `AccountSection.tsx`:

1. Add `onDirtyChange` to the props interface:
```typescript
interface AccountSectionProps {
  busy: boolean
  onSaving: (saving: boolean) => void
  onDirtyChange: (dirty: boolean) => void
}
```

2. Destructure:
```typescript
export default function AccountSection({ busy, onSaving, onDirtyChange }: AccountSectionProps) {
```

3. After the existing `profileChanged` computation (lines 42-44), add:
```typescript
const passwordDirty =
  currentPassword.length > 0 || newPassword.length > 0 || confirmPassword.length > 0
const isDirty = profileChanged || passwordDirty

useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])
useEffect(() => { return () => { onDirtyChange(false) } }, [onDirtyChange])
```

4. In `handleChangePassword`, before the logout call (lines 115-117), add `onDirtyChange(false)`:
```typescript
if (result.sessions_revoked === true) {
  onDirtyChange(false)
  void useAuthStore.getState().logout()
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/admin/AccountSection.tsx
git commit -m "feat: add onDirtyChange to AccountSection"
```

---

### Task 5: Add `onDirtyChange` and computed `orderDirty` to PagesSection

**Files:**
- Modify: `frontend/src/components/admin/PagesSection.tsx`

**Reference:** Currently `orderDirty` is a `useState(false)` at line 87, set to `true` in `handleMoveUp`/`handleMoveDown` (lines 119, 131), and reset to `false` in `handleSaveOrder` (line 145). The "Save Order" button is conditionally rendered at lines 483-493.

- [ ] **Step 1: Add `onDirtyChange` prop**

1. Add to props interface:
```typescript
interface PagesSectionProps {
  initialPages: AdminPageConfig[]
  busy: boolean
  onSaving: (saving: boolean) => void
  onPagesChange: (pages: AdminPageConfig[]) => void
  onDirtyChange: (dirty: boolean) => void
}
```

2. Destructure:
```typescript
export default function PagesSection({
  initialPages,
  busy,
  onSaving,
  onPagesChange,
  onDirtyChange,
}: PagesSectionProps) {
```

3. Add `useMemo` to the import from `react`.

- [ ] **Step 2: Replace `orderDirty` state with computed value**

1. Remove the `orderDirty` state declaration:
```typescript
// DELETE: const [orderDirty, setOrderDirty] = useState(false)
```

2. Add computed `initialPageIds` and `orderDirty`:
```typescript
const initialPageIds = useMemo(() => initialPages.map((p) => p.id), [initialPages])

const orderDirty =
  pages.length !== initialPageIds.length ||
  pages.some((p, i) => p.id !== initialPageIds[i])
```

3. Remove `setOrderDirty(true)` from `handleMoveUp` (line 119) and `handleMoveDown` (line 131).

4. Remove `setOrderDirty(false)` from `handleSaveOrder` (line 145).

- [ ] **Step 3: Add page edit dirty tracking and report combined dirty**

**Scoping note:** The spec mentions tracking edit dirty state regardless of expansion. However, the current `handleExpandPage` resets `editTitle`/`editContent` from server state whenever a page is re-expanded. This means edits are already lost on re-expand, so tracking dirty only when a page is expanded is consistent with actual behavior. Preserving per-page edit state across collapse would require a significant refactor (e.g., a `Map<string, {title, content}>`) beyond the scope of this feature.

After the `orderDirty` computation, add:
```typescript
const pageEditDirty = (() => {
  if (expandedPageId === null) return false
  const page = pages.find((p) => p.id === expandedPageId)
  if (!page) return false
  if (editTitle !== page.title) return true
  if (!BUILTIN_PAGE_IDS.has(page.id) && editContent !== (page.content ?? '')) return true
  return false
})()

const isDirty = orderDirty || pageEditDirty

useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])
useEffect(() => { return () => { onDirtyChange(false) } }, [onDirtyChange])
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/PagesSection.tsx
git commit -m "feat: add onDirtyChange and computed orderDirty to PagesSection"
```

---

### Task 6: Wire up AdminPage with dirty aggregation, hook, and tab switch guard

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

- [ ] **Step 1: Add dirty state aggregation and hook**

1. Add import:
```typescript
import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'
```

2. After the existing busy tracking state (lines 52-56), add dirty state:
```typescript
const [siteDirty, setSiteDirty] = useState(false)
const [pagesDirty, setPagesDirty] = useState(false)
const [accountDirty, setAccountDirty] = useState(false)
const anyDirty = siteDirty || pagesDirty || accountDirty
```

3. Call the hook (after the `anyDirty` declaration):
```typescript
useUnsavedChanges(anyDirty)
```

- [ ] **Step 2: Add tab switch guard**

Replace the tab button `onClick` (line 139) with a guarded handler. Add a function before the return statement:

```typescript
function handleTabSwitch(key: AdminTabKey) {
  if (anyDirty) {
    const leave = window.confirm('You have unsaved changes. Are you sure you want to leave?')
    if (!leave) return
  }
  setActiveTab(key)
}
```

Update the tab button `onClick` from `onClick={() => setActiveTab(tab.key)}` to `onClick={() => handleTabSwitch(tab.key)}`.

- [ ] **Step 3: Pass `onDirtyChange` to sub-sections**

Update the section renders to pass the callbacks:

```tsx
{activeTab === 'settings' && (
  <SiteSettingsSection
    initialSettings={siteSettings}
    busy={busy}
    onSaving={setSiteSaving}
    onSavedSettings={setSiteSettings}
    onDirtyChange={setSiteDirty}
  />
)}
{activeTab === 'pages' && (
  <PagesSection
    initialPages={pages}
    busy={busy}
    onSaving={setPagesSaving}
    onPagesChange={setPages}
    onDirtyChange={setPagesDirty}
  />
)}
{activeTab === 'account' && (
  <AccountSection busy={busy} onSaving={setAccountSaving} onDirtyChange={setAccountDirty} />
)}
```

SocialAccountsPanel is unchanged (no dirty tracking).

- [ ] **Step 4: Run frontend checks to verify no type errors**

Run: `just check-frontend`
Expected: PASS (existing tests should still pass; new behavior untested until next task)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat: add unsaved changes detection to AdminPage"
```

---

### Task 7: Admin dirty state tests

**Files:**
- Modify: `frontend/src/pages/__tests__/AdminPage.test.tsx`

**Important:** The existing test uses `MemoryRouter` which does not support `useBlocker`. Switch `renderAdmin` to use `createMemoryRouter` + `RouterProvider` so `useBlocker` works.

**Note on `useNavigate` mock:** The existing test mocks `useNavigate` via `vi.mock('react-router-dom', ...)` with `...actual` spread. This is compatible with `createMemoryRouter` because `useBlocker` uses the router context directly (not `useNavigate`), and the mock only replaces the `useNavigate` export. The `LabelSettingsPage.test.tsx` already demonstrates this pattern working. Existing auth-redirect tests that assert on `mockNavigate` continue to work.

- [ ] **Step 1: Update `renderAdmin` helper to use data router**

Replace the import and helper:

1. Change the import from `MemoryRouter` to include `createMemoryRouter, RouterProvider`:
```typescript
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
```

2. Add `createElement` import from `react`:
```typescript
import { createElement } from 'react'
```

3. Replace `renderAdmin`:
```typescript
function renderAdmin(path = '/admin') {
  const router = createMemoryRouter(
    [{ path: '/admin', element: createElement(AdminPage) }],
    { initialEntries: [path] },
  )
  return render(createElement(RouterProvider, { router }))
}
```

4. For the `?tab=` test, the path is `/admin?tab=social`. With `createMemoryRouter`, the initial entry can include query strings. Verify the existing `switchToTab` tests still pass.

- [ ] **Step 2: Run existing tests to verify the helper change doesn't break them**

Run: `just test-frontend -- --run frontend/src/pages/__tests__/AdminPage.test.tsx`
Expected: PASS — all existing tests should continue to pass with the new router setup

- [ ] **Step 3: Add dirty tracking and tab switch guard tests**

Add the following tests inside the existing `describe('AdminPage', ...)`:

```typescript
describe('unsaved changes', () => {
  it('site settings tab reports dirty when title changes', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.clear(screen.getByLabelText('Title *'))
    await user.type(screen.getByLabelText('Title *'), 'New Title')

    // Switching tabs should show confirm dialog
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: 'Pages' }))

    expect(confirmSpy).toHaveBeenCalledWith(
      'You have unsaved changes. Are you sure you want to leave?',
    )
    // Tab should NOT have switched since confirm returned false
    expect(screen.getByLabelText('Title *')).toBeInTheDocument()
    confirmSpy.mockRestore()
  })

  it('tab switch proceeds when user confirms', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.clear(screen.getByLabelText('Title *'))
    await user.type(screen.getByLabelText('Title *'), 'New Title')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Pages' }))

    expect(confirmSpy).toHaveBeenCalled()
    // Tab should have switched — Pages section should be visible
    await waitFor(() => {
      expect(screen.queryByLabelText('Title *')).not.toBeInTheDocument()
    })
    confirmSpy.mockRestore()
  })

  it('tab switch without dirty state does not show confirm dialog', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    const confirmSpy = vi.spyOn(window, 'confirm')
    await user.click(screen.getByRole('button', { name: 'Pages' }))

    expect(confirmSpy).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('account profile changes trigger dirty state', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    // Switch to Account tab (clean → no confirm)
    await user.click(screen.getByRole('button', { name: 'Account' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    await user.type(screen.getByLabelText('Username'), 'newname')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: 'Settings' }))

    expect(confirmSpy).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('account password field triggers dirty state', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.click(screen.getByRole('button', { name: 'Account' }))

    await waitFor(() => {
      expect(screen.getByLabelText(/current password/i)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/current password/i), 'secret')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: 'Settings' }))

    expect(confirmSpy).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('page reorder triggers dirty, reordering back clears it', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.click(screen.getByRole('button', { name: 'Pages' }))

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })

    // Move "Labels" up
    await user.click(screen.getByLabelText('Move Labels up'))

    // Save Order button should appear
    expect(screen.getByRole('button', { name: /save order/i })).toBeInTheDocument()

    // Move "Labels" back down → original order restored
    await user.click(screen.getByLabelText('Move Labels down'))

    // Save Order button should disappear
    expect(screen.queryByRole('button', { name: /save order/i })).not.toBeInTheDocument()

    // Tab switch should NOT show confirm (not dirty)
    const confirmSpy = vi.spyOn(window, 'confirm')
    await user.click(screen.getByRole('button', { name: 'Settings' }))
    expect(confirmSpy).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })
})
```

- [ ] **Step 4: Run tests**

Run: `just test-frontend -- --run frontend/src/pages/__tests__/AdminPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Run full checks**

Run: `just check-frontend`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/__tests__/AdminPage.test.tsx
git commit -m "test: add unsaved changes detection tests for AdminPage"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full project checks**

Run: `just check`
Expected: PASS

- [ ] **Step 2: Start dev server and manually verify**

Run: `just start`

Verify in browser:
1. Label Settings (`/labels/<id>/settings`): toggle a parent, try to navigate away → confirm dialog appears. Save → dialog does not appear.
2. Admin Settings tab: change title, switch tab → confirm dialog. Cancel → stays on tab. Confirm → switches.
3. Admin Account tab: type in password field, switch tab → confirm dialog.
4. Admin Pages tab: reorder pages, switch tab → confirm dialog. Reorder back → no dialog.

Run: `just stop`
