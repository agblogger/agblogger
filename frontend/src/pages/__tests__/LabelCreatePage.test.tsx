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
  useUnsavedChanges: (...args: unknown[]) => mockUseUnsavedChanges(...args) as { markSaved: () => void },
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
