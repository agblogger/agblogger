import { createElement, useEffect } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig, useSWRConfig } from 'swr'

import type { UserResponse, LabelResponse } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
})

const mockFetchLabel = vi.fn()
const mockFetchLabels = vi.fn()
const mockUpdateLabel = vi.fn()
const mockDeleteLabel = vi.fn()
const mockMarkSaved = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabel: (...args: unknown[]) => mockFetchLabel(...args) as unknown,
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
  updateLabel: (...args: unknown[]) => mockUpdateLabel(...args) as unknown,
  deleteLabel: (...args: unknown[]) => mockDeleteLabel(...args) as unknown,
}))

vi.mock('@/components/labels/graphUtils', () => ({
  computeDescendants: (_id: string, _map: unknown) => new Set<string>(),
}))

vi.mock('@/hooks/useUnsavedChanges', () => ({
  useUnsavedChanges: () => ({ markSaved: mockMarkSaved }),
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

import LabelSettingsPage from '../LabelSettingsPage'

const testLabel: LabelResponse = {
  id: 'swe',
  names: ['software engineering', 'programming'],
  is_implicit: false,
  parents: ['cs'],
  children: [],
  post_count: 5,
}

const allLabels: LabelResponse[] = [
  testLabel,
  { id: 'cs', names: ['computer science'], is_implicit: false, parents: [], children: ['swe'], post_count: 10 },
  { id: 'math', names: ['mathematics'], is_implicit: false, parents: [], children: [], post_count: 3 },
]

const multiParentLabel: LabelResponse = {
  ...testLabel,
  parents: ['cs', 'math'],
}

const allLabelsWithTwoParents: LabelResponse[] = [
  multiParentLabel,
  ...allLabels.slice(1),
]

function withPrimaryLabel(label: LabelResponse, labels: LabelResponse[] = allLabels): LabelResponse[] {
  return [label, ...labels.filter((candidate) => candidate.id !== label.id)]
}

let capturedMutate: ReturnType<typeof useSWRConfig>['mutate'] | null = null

function CaptureMutate() {
  const { mutate } = useSWRConfig()
  useEffect(() => {
    capturedMutate = mutate
  }, [mutate])
  return null
}

function renderSettings(labelId = 'swe') {
  const router = createMemoryRouter(
    [{ path: '/labels/:labelId/settings', element: createElement(LabelSettingsPage) }],
    { initialEntries: [`/labels/${labelId}/settings`] },
  )
  return render(
    createElement(SWRConfig, { value: { provider: () => new Map(), dedupingInterval: 0 } },
      createElement(CaptureMutate),
      createElement(RouterProvider, { router }),
    ),
  )
}

describe('LabelSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null }
    mockIsInitialized = true
    capturedMutate = null
  })

  it('redirects to login when unauthenticated', () => {
    mockUser = null
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderSettings()
    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
    expect(mockFetchLabel).not.toHaveBeenCalled()
  })

  it('shows spinner while loading', () => {
    mockFetchLabel.mockReturnValue(new Promise(() => {}))
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderSettings()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows 404 error', async () => {
    mockFetchLabels.mockResolvedValue([])
    mockFetchLabel.mockRejectedValue(mockHttpError(404))
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Label not found.')).toBeInTheDocument()
    })
  })

  it('shows 401 error', async () => {
    mockFetchLabels.mockRejectedValue(
      mockHttpError(401),
    )
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows generic error', async () => {
    mockFetchLabels.mockRejectedValue(new Error('Network'))
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Failed to load label data. Please try again later.')).toBeInTheDocument()
    })
  })

  it('loads and displays label names', async () => {
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })
    expect(screen.getByText('programming')).toBeInTheDocument()
  })

  it('hydrates the selected label from the loaded label collection without fetching label detail', async () => {
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    expect(mockFetchLabel).not.toHaveBeenCalled()
  })

  it('falls back to label detail when the shared labels collection misses the selected label', async () => {
    mockFetchLabels.mockResolvedValue(allLabels.filter((label) => label.id !== 'swe'))
    mockFetchLabel.mockResolvedValue(testLabel)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    expect(mockFetchLabel).toHaveBeenCalledWith('swe')
  })

  it('reprocesses the selected label when labels revalidate with fresh server data', async () => {
    mockFetchLabels
      .mockResolvedValueOnce(allLabels)
      .mockResolvedValueOnce(withPrimaryLabel({ ...testLabel, names: ['software craftsmanship'], parents: ['math'] }))
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(capturedMutate).not.toBeNull()
    })

    await act(async () => {
      await capturedMutate!(['labels', 1])
    })

    await waitFor(() => {
      expect(screen.getByText('software craftsmanship')).toBeInTheDocument()
    })
    expect(screen.queryByText('software engineering')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /#math/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /#cs/i })).not.toBeChecked()
  })

  it('shows not found when labels revalidate without the selected label', async () => {
    mockFetchLabels
      .mockResolvedValueOnce(allLabels)
      .mockResolvedValueOnce(allLabels.filter((label) => label.id !== 'swe'))
    mockFetchLabel.mockRejectedValue(mockHttpError(404))
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(capturedMutate).not.toBeNull()
    })

    await act(async () => {
      await capturedMutate!(['labels', 1])
    })

    await waitFor(() => {
      expect(screen.getByText('Label not found.')).toBeInTheDocument()
    })
  })

  it('removes a name (but not if only one left)', async () => {
    const singleNameLabel = { ...testLabel, names: ['only-name'] }
    mockFetchLabels.mockResolvedValue(withPrimaryLabel(singleNameLabel))
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('only-name')).toBeInTheDocument()
    })

    // The remove button should be disabled when only 1 name remains
    const removeBtn = screen.getByLabelText('Remove name "only-name"')
    expect(removeBtn).toBeEnabled()
  })

  it('adds a name', async () => {
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Add a display name...'), 'coding')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(screen.getByText('coding')).toBeInTheDocument()
  })

  it('rejects empty/duplicate names', async () => {
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    // Add a duplicate
    await user.type(screen.getByPlaceholderText('Add a display name...'), 'software engineering')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // Should not duplicate - count should remain 2
    expect(screen.getAllByText('software engineering')).toHaveLength(1)
  })

  it('adds name on Enter key', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    const input = screen.getByPlaceholderText('Add a display name...')
    await user.type(input, 'dev{Enter}')

    expect(screen.getByText('dev')).toBeInTheDocument()
  })

  it('toggles parent labels', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('#cs')).toBeInTheDocument()
    })

    // cs should be checked (it's a parent)
    const csCheckbox = screen.getByRole('checkbox', { name: /#cs/i })
    expect(csCheckbox).toBeChecked()

    // Uncheck cs
    await user.click(csCheckbox)
    expect(csCheckbox).not.toBeChecked()
  })

  it('saves label changes', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    mockUpdateLabel.mockResolvedValue(testLabel)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    // Toggle math parent to make form dirty
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

  it('shows 409 cycle error on save', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    mockUpdateLabel.mockRejectedValue(
      mockHttpError(409),
    )
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    // Toggle math parent to make form dirty
    const mathCheckbox = screen.getByRole('checkbox', { name: /#math/i })
    await user.click(mathCheckbox)

    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(screen.getByText(/create a cycle/i)).toBeInTheDocument()
    })
  })

  it('deletes label with confirmation', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    mockDeleteLabel.mockResolvedValue({ id: 'swe', deleted: true })
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /delete label/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /delete label/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/labels', { replace: true })
    })
  })

  it('marks the form saved before redirecting after successful delete', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    mockDeleteLabel.mockResolvedValue({ id: 'swe', deleted: true })
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('checkbox', { name: /#math/i }))
    await user.click(screen.getByRole('button', { name: /delete label/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => {
      expect(mockMarkSaved).toHaveBeenCalledTimes(1)
      expect(mockNavigate).toHaveBeenCalledWith('/labels', { replace: true })
    })

    const markSavedCallOrder = mockMarkSaved.mock.invocationCallOrder[0]
    const navigateCallOrder = mockNavigate.mock.invocationCallOrder[0]
    if (markSavedCallOrder === undefined || navigateCallOrder === undefined) {
      throw new Error('Expected markSaved and navigate to be called')
    }
    expect(markSavedCallOrder).toBeLessThan(navigateCallOrder)
  })

  it('allows saving with no display names', async () => {
    mockFetchLabels.mockResolvedValue(withPrimaryLabel({ ...testLabel, names: [] }))
    mockUpdateLabel.mockResolvedValue({ ...testLabel, names: [], parents: ['cs', 'math'] })
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
    })

    // Toggle math parent to make form dirty
    const mathCheckbox = screen.getByRole('checkbox', { name: /#math/i })
    await user.click(mathCheckbox)

    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() => {
      expect(mockUpdateLabel).toHaveBeenCalledWith('swe', { names: [], parents: ['cs', 'math'] })
    })
    expect(screen.queryByText('At least one display name is required.')).not.toBeInTheDocument()
  })

  it('shows Display Names heading without required indicator', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    expect(screen.getByRole('heading', { level: 2, name: 'Display Names' })).toBeInTheDocument()
    expect(screen.queryByText(/at least one display name is required/i)).not.toBeInTheDocument()
  })

  it('cancels delete confirmation', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /delete label/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /delete label/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByRole('button', { name: /confirm delete/i })).not.toBeInTheDocument()
  })

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
    expect(mockMarkSaved).toHaveBeenCalled()
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

  it('removing and re-adding a name keeps save enabled when alias order changes', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    // Remove first name → dirty
    await user.click(screen.getByLabelText('Remove name "software engineering"'))
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()

    // Re-add it (appended to end, so order is now ['programming', 'software engineering'])
    await user.type(screen.getByPlaceholderText('Add a display name...'), 'software engineering')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // Same aliases but different order still changes the primary display name.
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()
  })

  it('reverting a multi-parent selection back to the original set disables save even if order changes', async () => {
    mockFetchLabels.mockResolvedValue(allLabelsWithTwoParents)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('#cs')).toBeInTheDocument()
    })

    const csCheckbox = screen.getByRole('checkbox', { name: /#cs/i })

    await user.click(csCheckbox)
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()

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
})
