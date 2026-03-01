import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, LabelResponse } from '@/api/client'

vi.mock('@/api/client', () => {
  class HTTPError extends Error {
    response: { status: number }
    constructor(status: number) {
      super(`HTTP ${status}`)
      this.response = { status }
    }
  }
  return { default: {}, HTTPError }
})

const mockFetchLabel = vi.fn()
const mockFetchLabels = vi.fn()
const mockUpdateLabel = vi.fn()
const mockDeleteLabel = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabel: (...args: unknown[]) => mockFetchLabel(...args) as unknown,
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
  updateLabel: (...args: unknown[]) => mockUpdateLabel(...args) as unknown,
  deleteLabel: (...args: unknown[]) => mockDeleteLabel(...args) as unknown,
}))

vi.mock('@/components/labels/graphUtils', () => ({
  computeDescendants: (_id: string, _map: unknown) => new Set<string>(),
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

const { HTTPError: MockHTTPError } = await import('@/api/client')

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

function renderSettings(labelId = 'swe') {
  const router = createMemoryRouter(
    [{ path: '/labels/:labelId/settings', element: createElement(LabelSettingsPage) }],
    { initialEntries: [`/labels/${labelId}/settings`] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('LabelSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockIsInitialized = true
  })

  it('redirects to login when unauthenticated', () => {
    mockUser = null
    mockFetchLabel.mockReturnValue(new Promise(() => {}))
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderSettings()
    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
  })

  it('shows spinner while loading', () => {
    mockFetchLabel.mockReturnValue(new Promise(() => {}))
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderSettings()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows 404 error', async () => {
    mockFetchLabel.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(404),
    )
    mockFetchLabels.mockResolvedValue([])
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Label not found.')).toBeInTheDocument()
    })
  })

  it('shows 401 error', async () => {
    mockFetchLabel.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    mockFetchLabels.mockResolvedValue([])
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows generic error', async () => {
    mockFetchLabel.mockRejectedValue(new Error('Network'))
    mockFetchLabels.mockResolvedValue([])
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('Failed to load label data. Please try again later.')).toBeInTheDocument()
    })
  })

  it('loads and displays label names', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })
    expect(screen.getByText('programming')).toBeInTheDocument()
  })

  it('removes a name (but not if only one left)', async () => {
    const singleNameLabel = { ...testLabel, names: ['only-name'] }
    mockFetchLabel.mockResolvedValue(singleNameLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('only-name')).toBeInTheDocument()
    })

    // The remove button should be disabled when only 1 name remains
    const removeBtn = screen.getByLabelText('Remove name "only-name"')
    expect(removeBtn).toBeDisabled()
  })

  it('adds a name', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
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
    mockFetchLabel.mockResolvedValue(testLabel)
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

    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(mockUpdateLabel).toHaveBeenCalledWith('swe', {
        names: ['software engineering', 'programming'],
        parents: ['cs'],
      })
    })
  })

  it('shows 409 cycle error on save', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    mockUpdateLabel.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(409),
    )
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

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

  it('clears error when user adds a name', async () => {
    mockFetchLabel.mockResolvedValue({ ...testLabel, names: [] })
    mockFetchLabels.mockResolvedValue(allLabels)
    const user = userEvent.setup()
    renderSettings()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
    })

    // Trigger validation error — error + hint text both contain the message
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    expect(screen.getAllByText('At least one display name is required.')).toHaveLength(2)

    // Type a name and add it
    await user.type(screen.getByPlaceholderText('Add a display name...'), 'test-name')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // Error banner should be gone, only the hint text remains
    expect(screen.getAllByText('At least one display name is required.')).toHaveLength(1)
  })

  it('shows required indicator on Display Names heading', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabels.mockResolvedValue(allLabels)
    renderSettings()

    await waitFor(() => {
      expect(screen.getByText('software engineering')).toBeInTheDocument()
    })

    const heading = screen.getByText((content, element) => {
      return element?.tagName === 'H2' && content.includes('Display Names') && content.includes('*')
    })
    expect(heading).toBeInTheDocument()
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
})
