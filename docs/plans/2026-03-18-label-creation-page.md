# Label Creation Page Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/labels/new` page for creating labels, extracting shared form components from the existing `LabelSettingsPage`.

**Architecture:** Extract `LabelNamesEditor` and `LabelParentsSelector` from `LabelSettingsPage` into shared components under `frontend/src/components/labels/`. Create a new `LabelCreatePage` that reuses them. Add a "+ New Label" button to `LabelsPage` (auth-gated). Route `/labels/new` must precede `/labels/:labelId` in the router.

**Tech Stack:** React, TypeScript, Vitest, React Testing Library, React Router, Tailwind CSS, lucide-react

**Spec:** `docs/specs/2026-03-18-label-creation-page-design.md`

---

## Chunk 1: Shared Components

### Task 1: LabelNamesEditor

**Files:**
- Create: `frontend/src/components/labels/LabelNamesEditor.tsx`
- Test: `frontend/src/components/labels/__tests__/LabelNamesEditor.test.tsx`

- [ ] **Step 1: Write tests for LabelNamesEditor**

```typescript
// frontend/src/components/labels/__tests__/LabelNamesEditor.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import LabelNamesEditor from '../LabelNamesEditor'

describe('LabelNamesEditor', () => {
  it('renders existing names as tags', () => {
    render(<LabelNamesEditor names={['python', 'py']} onNamesChange={vi.fn()} disabled={false} />)
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByText('py')).toBeInTheDocument()
  })

  it('adds a new name on button click', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['existing']} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'new-name')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).toHaveBeenCalledWith(['existing', 'new-name'])
  })

  it('adds a new name on Enter key', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'entered{Enter}')

    expect(onNamesChange).toHaveBeenCalledWith(['entered'])
  })

  it('removes a name when remove button is clicked', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['keep', 'remove']} onNamesChange={onNamesChange} disabled={false} />)

    await user.click(screen.getByLabelText('Remove name "remove"'))

    expect(onNamesChange).toHaveBeenCalledWith(['keep'])
  })

  it('prevents adding duplicate names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={['existing']} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'existing')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).not.toHaveBeenCalled()
  })

  it('disables all controls when disabled is true', () => {
    render(<LabelNamesEditor names={['test']} onNamesChange={vi.fn()} disabled={true} />)

    expect(screen.getByPlaceholderText('Add a display name...')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
    expect(screen.getByLabelText('Remove name "test"')).toBeDisabled()
  })

  it('trims whitespace from new names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.type(screen.getByPlaceholderText('Add a display name...'), '  spaced  ')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).toHaveBeenCalledWith(['spaced'])
  })

  it('does not add empty names', async () => {
    const onNamesChange = vi.fn()
    const user = userEvent.setup()
    render(<LabelNamesEditor names={[]} onNamesChange={onNamesChange} disabled={false} />)

    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onNamesChange).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelNamesEditor.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement LabelNamesEditor**

```typescript
// frontend/src/components/labels/LabelNamesEditor.tsx
import { useState } from 'react'
import { X } from 'lucide-react'

interface LabelNamesEditorProps {
  names: string[]
  onNamesChange: (names: string[]) => void
  disabled: boolean
}

export default function LabelNamesEditor({ names, onNamesChange, disabled }: LabelNamesEditorProps) {
  const [newName, setNewName] = useState('')

  function handleAdd() {
    const trimmed = newName.trim()
    if (!trimmed) return
    if (names.includes(trimmed)) return
    onNamesChange([...names, trimmed])
    setNewName('')
  }

  function handleRemove(index: number) {
    onNamesChange(names.filter((_, i) => i !== index))
  }

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <h2 className="text-sm font-medium text-ink mb-3">Display Names</h2>
      <div className="flex flex-wrap gap-2 mb-3">
        {names.map((name, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm
                     bg-tag-bg text-tag-text rounded-full"
          >
            {name}
            <button
              onClick={() => handleRemove(i)}
              disabled={disabled}
              className="ml-0.5 p-0.5 rounded-full hover:bg-black/10 disabled:opacity-30
                       transition-colors"
              aria-label={`Remove name "${name}"`}
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleAdd()
            }
          }}
          disabled={disabled}
          placeholder="Add a display name..."
          className="flex-1 px-3 py-2 bg-paper-warm border border-border rounded-lg
                   text-ink text-sm
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50"
        />
        <button
          onClick={handleAdd}
          disabled={disabled || newName.trim().length === 0}
          className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                   hover:bg-paper-warm disabled:opacity-50 transition-colors"
        >
          Add
        </button>
      </div>
      <p className="text-xs text-muted mt-2">Optional aliases shown alongside the label ID.</p>
    </section>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelNamesEditor.test.tsx`
Expected: PASS — all 8 tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/labels/LabelNamesEditor.tsx frontend/src/components/labels/__tests__/LabelNamesEditor.test.tsx
git commit -m "feat: add LabelNamesEditor shared component"
```

---

### Task 2: LabelParentsSelector

**Files:**
- Create: `frontend/src/components/labels/LabelParentsSelector.tsx`
- Test: `frontend/src/components/labels/__tests__/LabelParentsSelector.test.tsx`

- [ ] **Step 1: Write tests for LabelParentsSelector**

```typescript
// frontend/src/components/labels/__tests__/LabelParentsSelector.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import LabelParentsSelector from '../LabelParentsSelector'
import type { LabelResponse } from '@/api/client'

const sampleLabels: LabelResponse[] = [
  { id: 'python', names: ['programming'], is_implicit: false, parents: [], children: [], post_count: 5 },
  { id: 'web', names: [], is_implicit: false, parents: [], children: [], post_count: 3 },
  { id: 'async', names: ['async', 'asynchronous'], is_implicit: false, parents: [], children: [], post_count: 1 },
]

describe('LabelParentsSelector', () => {
  it('renders available parent labels with checkboxes', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    expect(screen.getByText('#python')).toBeInTheDocument()
    expect(screen.getByText('#web')).toBeInTheDocument()
    expect(screen.getByText('#async')).toBeInTheDocument()
    expect(screen.getByText('(programming)')).toBeInTheDocument()
    expect(screen.getByText('(async, asynchronous)')).toBeInTheDocument()
  })

  it('checks already-selected parents', () => {
    render(
      <LabelParentsSelector
        parents={['python']}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[0]).toBeChecked() // python
    expect(checkboxes[1]).not.toBeChecked() // web
  })

  it('calls onParentsChange with added parent on check', async () => {
    const onParentsChange = vi.fn()
    const user = userEvent.setup()
    render(
      <LabelParentsSelector
        parents={['python']}
        onParentsChange={onParentsChange}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    await user.click(screen.getAllByRole('checkbox')[1]) // check 'web'

    expect(onParentsChange).toHaveBeenCalledWith(['python', 'web'])
  })

  it('calls onParentsChange with removed parent on uncheck', async () => {
    const onParentsChange = vi.fn()
    const user = userEvent.setup()
    render(
      <LabelParentsSelector
        parents={['python', 'web']}
        onParentsChange={onParentsChange}
        availableParents={sampleLabels}
        disabled={false}
      />
    )

    await user.click(screen.getAllByRole('checkbox')[0]) // uncheck 'python'

    expect(onParentsChange).toHaveBeenCalledWith(['web'])
  })

  it('shows empty message when no parents available', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={[]}
        disabled={false}
      />
    )

    expect(screen.getByText('No other labels available as parents.')).toBeInTheDocument()
  })

  it('disables all checkboxes when disabled is true', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={true}
      />
    )

    screen.getAllByRole('checkbox').forEach((cb) => {
      expect(cb).toBeDisabled()
    })
  })

  it('renders hint text when provided', () => {
    render(
      <LabelParentsSelector
        parents={[]}
        onParentsChange={vi.fn()}
        availableParents={sampleLabels}
        disabled={false}
        hint="Descendants excluded to prevent cycles."
      />
    )

    expect(screen.getByText('Descendants excluded to prevent cycles.')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelParentsSelector.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement LabelParentsSelector**

```typescript
// frontend/src/components/labels/LabelParentsSelector.tsx
import type { LabelResponse } from '@/api/client'

interface LabelParentsSelectorProps {
  parents: string[]
  onParentsChange: (parents: string[]) => void
  availableParents: LabelResponse[]
  disabled: boolean
  hint?: string
}

export default function LabelParentsSelector({
  parents,
  onParentsChange,
  availableParents,
  disabled,
  hint,
}: LabelParentsSelectorProps) {
  function handleToggle(parentId: string) {
    if (parents.includes(parentId)) {
      onParentsChange(parents.filter((p) => p !== parentId))
    } else {
      onParentsChange([...parents, parentId])
    }
  }

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <h2 className="text-sm font-medium text-ink mb-3">Parent Labels</h2>
      {availableParents.length === 0 ? (
        <p className="text-sm text-muted">No other labels available as parents.</p>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {availableParents.map((candidate) => (
            <label
              key={candidate.id}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-paper-warm
                       cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={parents.includes(candidate.id)}
                onChange={() => handleToggle(candidate.id)}
                disabled={disabled}
                className="rounded border-border text-accent focus:ring-accent/20"
              />
              <span className="text-sm text-ink">#{candidate.id}</span>
              {candidate.names.length > 0 && (
                <span className="text-xs text-muted">({candidate.names.join(', ')})</span>
              )}
            </label>
          ))}
        </div>
      )}
      {hint && <p className="text-xs text-muted mt-2">{hint}</p>}
    </section>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/labels/__tests__/LabelParentsSelector.test.tsx`
Expected: PASS — all 7 tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/labels/LabelParentsSelector.tsx frontend/src/components/labels/__tests__/LabelParentsSelector.test.tsx
git commit -m "feat: add LabelParentsSelector shared component"
```

---

## Chunk 2: Refactor Settings + Create Page + Route

### Task 3: Refactor LabelSettingsPage to use shared components

**Files:**
- Modify: `frontend/src/pages/LabelSettingsPage.tsx`
- Existing test: `frontend/src/pages/__tests__/LabelSettingsPage.test.tsx` (must continue to pass, no changes)

- [ ] **Step 1: Run existing LabelSettingsPage tests to establish baseline**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelSettingsPage.test.tsx`
Expected: PASS — all tests green (baseline)

- [ ] **Step 2: Refactor LabelSettingsPage**

Replace the inline names and parents sections with the shared components. In `frontend/src/pages/LabelSettingsPage.tsx`:

**Remove** the `newName` state (line 44), the `handleRemoveName` function (lines 102-105), the `handleAddName` function (lines 107-114), and the `handleToggleParent` function (lines 116-123).

**Remove** the `X` import from lucide-react (line 7) — only `Settings` and `Trash2` are still needed.

**Add imports:**
```typescript
import LabelNamesEditor from '@/components/labels/LabelNamesEditor'
import LabelParentsSelector from '@/components/labels/LabelParentsSelector'
```

**Replace** the names `<section>` (lines 214-265) with:
```tsx
<LabelNamesEditor
  names={names}
  onNamesChange={(updated) => { setNames(updated); setError(null) }}
  disabled={busy}
/>
```

**Replace** the parents `<section>` (lines 267-298) with:
```tsx
<LabelParentsSelector
  parents={parents}
  onParentsChange={(updated) => { setParents(updated); setError(null) }}
  availableParents={availableParents}
  disabled={busy}
  hint={`Labels that are descendants of #${labelId} are excluded to prevent cycles.`}
/>
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelSettingsPage.test.tsx`
Expected: PASS — all existing tests still green

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LabelSettingsPage.tsx
git commit -m "refactor: use shared LabelNamesEditor and LabelParentsSelector in LabelSettingsPage"
```

---

### Task 4: LabelCreatePage

**Files:**
- Create: `frontend/src/pages/LabelCreatePage.tsx`
- Create: `frontend/src/pages/__tests__/LabelCreatePage.test.tsx`

- [ ] **Step 1: Write tests for LabelCreatePage**

The test file uses `createMemoryRouter` + `RouterProvider` following the same pattern as `LabelSettingsPage.test.tsx`. Uses `MockHTTPError` from `@/test/MockHTTPError` and mutable `mockUser`/`mockIsInitialized` variables for auth state.

```typescript
// frontend/src/pages/__tests__/LabelCreatePage.test.tsx
import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, LabelResponse } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
})

const mockCreateLabel = vi.fn()
const mockFetchLabels = vi.fn()
const mockMarkSaved = vi.fn()
const mockUseUnsavedChanges = vi.fn()

vi.mock('@/api/labels', () => ({
  createLabel: (...args: unknown[]) => mockCreateLabel(...args) as unknown,
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
}))

vi.mock('@/hooks/useUnsavedChanges', () => ({
  useUnsavedChanges: (...args: unknown[]) => mockUseUnsavedChanges(...args),
}))

let mockUser: UserResponse | null = null
let mockIsInitialized = true

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null; isInitialized: boolean }) => unknown) =>
    selector({ user: mockUser, isInitialized: mockIsInitialized }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import LabelCreatePage from '../LabelCreatePage'

const allLabels: LabelResponse[] = [
  { id: 'python', names: ['programming'], is_implicit: false, parents: [], children: ['async'], post_count: 5 },
  { id: 'web', names: [], is_implicit: false, parents: [], children: [], post_count: 3 },
]

function renderCreatePage() {
  const router = createMemoryRouter(
    [{ path: '/labels/new', element: createElement(LabelCreatePage) }],
    { initialEntries: ['/labels/new'] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('LabelCreatePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockIsInitialized = true
    mockFetchLabels.mockResolvedValue(allLabels)
    mockUseUnsavedChanges.mockReturnValue({ markSaved: mockMarkSaved })
  })

  it('redirects to login when unauthenticated', () => {
    mockUser = null
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderCreatePage()
    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
  })

  it('renders the create label form', async () => {
    renderCreatePage()
    expect(await screen.findByText('New Label')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('e.g. machine-learning')).toBeInTheDocument()
    expect(screen.getByText('Display Names')).toBeInTheDocument()
    expect(screen.getByText('Parent Labels')).toBeInTheDocument()
  })

  it('disables Create button when label ID is empty', async () => {
    renderCreatePage()
    expect(await screen.findByRole('button', { name: 'Create Label' })).toBeDisabled()
  })

  it('disables Create button when label ID has invalid characters', async () => {
    const user = userEvent.setup()
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'Invalid!')

    expect(screen.getByRole('button', { name: 'Create Label' })).toBeDisabled()
  })

  it('enables Create button when label ID is valid', async () => {
    const user = userEvent.setup()
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'valid-label')

    expect(screen.getByRole('button', { name: 'Create Label' })).toBeEnabled()
  })

  it('creates label and navigates on success', async () => {
    const user = userEvent.setup()
    const created: LabelResponse = {
      id: 'new-label', names: [], is_implicit: false, parents: [], children: [], post_count: 0,
    }
    mockCreateLabel.mockResolvedValue(created)
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'new-label')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    await waitFor(() => {
      expect(mockCreateLabel).toHaveBeenCalledWith({ id: 'new-label', names: [], parents: [] })
    })
    expect(mockMarkSaved).toHaveBeenCalled()
    expect(mockNavigate).toHaveBeenCalledWith('/labels/new-label')
  })

  it('shows error on 409 conflict', async () => {
    const user = userEvent.setup()
    mockCreateLabel.mockRejectedValue(mockHttpError(409))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'duplicate')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    expect(await screen.findByText('A label with this ID already exists.')).toBeInTheDocument()
  })

  it('shows error on 422 validation error', async () => {
    const user = userEvent.setup()
    mockCreateLabel.mockRejectedValue(mockHttpError(422))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'test-id')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    expect(await screen.findByText('Invalid label ID. Use lowercase letters, numbers, and hyphens.')).toBeInTheDocument()
  })

  it('shows error on 404 parent not found', async () => {
    const user = userEvent.setup()
    mockCreateLabel.mockRejectedValue(mockHttpError(404))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'test-id')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    expect(await screen.findByText('One or more selected parent labels no longer exist.')).toBeInTheDocument()
  })

  it('shows error on 401 auth expired', async () => {
    const user = userEvent.setup()
    mockCreateLabel.mockRejectedValue(mockHttpError(401))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'test-id')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    expect(await screen.findByText('Session expired. Please log in again.')).toBeInTheDocument()
  })

  it('shows generic error on unknown failure', async () => {
    const user = userEvent.setup()
    mockCreateLabel.mockRejectedValue(new Error('network'))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'test-id')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    expect(await screen.findByText('Failed to create label. Please try again.')).toBeInTheDocument()
  })

  it('shows available parent labels', async () => {
    renderCreatePage()
    expect(await screen.findByText('#python')).toBeInTheDocument()
    expect(screen.getByText('#web')).toBeInTheDocument()
  })

  it('disables form controls while creating', async () => {
    const user = userEvent.setup()
    // Never-resolving promise to keep the creating state active
    mockCreateLabel.mockReturnValue(new Promise(() => {}))
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'test-id')
    await user.click(screen.getByRole('button', { name: 'Create Label' }))

    await waitFor(() => {
      expect(screen.getByText('Creating...')).toBeInTheDocument()
    })
  })

  it('passes isDirty=true to useUnsavedChanges when form has data', async () => {
    const user = userEvent.setup()
    renderCreatePage()
    await screen.findByText('New Label')

    await user.type(screen.getByPlaceholderText('e.g. machine-learning'), 'some-id')

    // useUnsavedChanges should have been called with isDirty=true
    const lastCall = mockUseUnsavedChanges.mock.calls.at(-1)
    expect(lastCall?.[0]).toBe(true)
  })

  it('passes isDirty=false to useUnsavedChanges when form is empty', async () => {
    renderCreatePage()
    await screen.findByText('New Label')

    // Initial render with empty form — isDirty should be false
    const firstCall = mockUseUnsavedChanges.mock.calls[0]
    expect(firstCall?.[0]).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelCreatePage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement LabelCreatePage**

```typescript
// frontend/src/pages/LabelCreatePage.tsx
import { useEffect, useMemo, useState } from 'react'
import AlertBanner from '@/components/AlertBanner'
import LoadingSpinner from '@/components/LoadingSpinner'
import BackLink from '@/components/BackLink'
import { useNavigate } from 'react-router-dom'
import { Tag } from 'lucide-react'

import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'
import { useAuthStore } from '@/stores/authStore'
import { createLabel, fetchLabels } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse } from '@/api/client'
import LabelNamesEditor from '@/components/labels/LabelNamesEditor'
import LabelParentsSelector from '@/components/labels/LabelParentsSelector'

const LABEL_ID_REGEX = /^[a-z0-9][a-z0-9-]*$/

export default function LabelCreatePage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  const [allLabels, setAllLabels] = useState<LabelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [labelId, setLabelId] = useState('')
  const [names, setNames] = useState<string[]>([])
  const [parents, setParents] = useState<string[]>([])
  const [creating, setCreating] = useState(false)

  const isValidId = labelId.length > 0 && labelId.length <= 100 && LABEL_ID_REGEX.test(labelId)

  const isDirty = useMemo(
    () => labelId.length > 0 || names.length > 0 || parents.length > 0,
    [labelId, names, parents],
  )

  const { markSaved } = useUnsavedChanges(isDirty)

  useEffect(() => {
    if (isInitialized && !user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  useEffect(() => {
    fetchLabels()
      .then(setAllLabels)
      .catch(() => {
        setError('Failed to load labels. Please try again later.')
      })
      .finally(() => setLoading(false))
  }, [])

  async function handleCreate() {
    if (!isValidId) return
    setCreating(true)
    setError(null)
    try {
      await createLabel({ id: labelId, names, parents })
      markSaved()
      void navigate(`/labels/${labelId}`)
    } catch (err) {
      if (err instanceof HTTPError) {
        const status = err.response.status
        if (status === 409) {
          setError('A label with this ID already exists.')
        } else if (status === 422) {
          setError('Invalid label ID. Use lowercase letters, numbers, and hyphens.')
        } else if (status === 404) {
          setError('One or more selected parent labels no longer exist.')
        } else if (status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          setError('Failed to create label. Please try again.')
        }
      } else {
        setError('Failed to create label. Please try again.')
      }
    } finally {
      setCreating(false)
    }
  }

  if (!isInitialized || !user) {
    return null
  }

  if (loading) {
    return <LoadingSpinner />
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <BackLink to="/labels" label="Back to labels" />
      </div>

      <div className="flex items-center gap-3 mb-8">
        <Tag size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">New Label</h1>
        <div className="ml-auto">
          <button
            onClick={() => void handleCreate()}
            disabled={creating || !isValidId}
            className="px-6 py-2.5 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            {creating ? 'Creating...' : 'Create Label'}
          </button>
        </div>
      </div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-6">{error}</AlertBanner>
      )}

      {/* Label ID section */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <h2 className="text-sm font-medium text-ink mb-3">Label ID</h2>
        <input
          type="text"
          value={labelId}
          onChange={(e) => { setLabelId(e.target.value); setError(null) }}
          disabled={creating}
          maxLength={100}
          placeholder="e.g. machine-learning"
          aria-describedby="label-id-hint"
          className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                   text-ink text-sm
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50"
        />
        <p id="label-id-hint" className="text-xs text-muted mt-2">
          Lowercase letters, numbers, and hyphens. Cannot be changed after creation.
        </p>
      </section>

      <LabelNamesEditor
        names={names}
        onNamesChange={(updated) => { setNames(updated); setError(null) }}
        disabled={creating}
      />

      <LabelParentsSelector
        parents={parents}
        onParentsChange={(updated) => { setParents(updated); setError(null) }}
        availableParents={allLabels}
        disabled={creating}
      />
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelCreatePage.test.tsx`
Expected: PASS — all tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LabelCreatePage.tsx frontend/src/pages/__tests__/LabelCreatePage.test.tsx
git commit -m "feat: add LabelCreatePage with tests"
```

---

### Task 5: Route and LabelsPage button

**Files:**
- Modify: `frontend/src/App.tsx:88` — add route before `:labelId`
- Modify: `frontend/src/pages/LabelsPage.tsx:56-70` — add New Label button
- Modify: `frontend/src/pages/__tests__/LabelsPage.test.tsx` — add button visibility tests

- [ ] **Step 1: Write tests for the New Label button visibility**

Add two test cases to the existing `frontend/src/pages/__tests__/LabelsPage.test.tsx`. The existing test file uses a mutable `mockUser` variable (line 22) that is set per-test. The `beforeEach` block sets `mockFetchLabels.mockResolvedValue(sampleLabels)`. Add these tests inside the existing `describe('LabelsPage', ...)` block:

```typescript
it('shows New Label button when user is authenticated', async () => {
  mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
  renderLabelsPage()
  expect(await screen.findByRole('link', { name: /new label/i })).toBeInTheDocument()
})

it('hides New Label button when user is not authenticated', async () => {
  mockUser = null
  renderLabelsPage()
  await screen.findByText('#cs')
  expect(screen.queryByRole('link', { name: /new label/i })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelsPage.test.tsx`
Expected: New tests FAIL — no element with "new label" found

- [ ] **Step 3: Add route in App.tsx**

In `frontend/src/App.tsx`, add the `/labels/new` route **before** the `/labels/:labelId` route (before line 89):

```typescript
{ path: "/labels/new", element: <LabelCreatePage /> },
```

Add the import at the top of the file:

```typescript
import LabelCreatePage from '@/pages/LabelCreatePage'
```

- [ ] **Step 4: Add New Label button to LabelsPage**

In `frontend/src/pages/LabelsPage.tsx`, add a `Plus` import from lucide-react and import `useAuthStore`. Inside the header `<div>` (around line 56), add the button between the view toggle and the search input:

```tsx
{user && (
  <Link
    to="/labels/new"
    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
             bg-accent text-white rounded-lg hover:bg-accent-light transition-colors"
  >
    <Plus size={16} />
    New Label
  </Link>
)}
```

The `user` variable comes from `useAuthStore((s) => s.user)` — add this to the `LabelsPage` component (not just `LabelListView` where it's currently used).

- [ ] **Step 5: Run all labels-related tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/LabelsPage.test.tsx src/pages/__tests__/LabelSettingsPage.test.tsx src/pages/__tests__/LabelCreatePage.test.tsx src/components/labels/__tests__/`
Expected: PASS — all tests green

- [ ] **Step 6: Run full frontend checks**

Run: `just check-frontend`
Expected: PASS — all static checks and tests pass

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/LabelsPage.tsx frontend/src/pages/__tests__/LabelsPage.test.tsx
git commit -m "feat: add /labels/new route and New Label button to LabelsPage"
```
