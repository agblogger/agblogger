import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, AdminSiteSettings, AdminPageConfig } from '@/api/client'

vi.mock('@/api/client', () => {
  class HTTPError extends Error {
    response: { status: number; text: () => Promise<string>; json: () => Promise<unknown> }
    constructor(status: number, body?: string) {
      super(`HTTP ${status}`)
      const bodyStr = body ?? ''
      this.response = {
        status,
        text: () => Promise.resolve(bodyStr),
        json: () => {
          try {
            return Promise.resolve(JSON.parse(bodyStr || '{}'))
          } catch {
            return Promise.reject(new SyntaxError('Failed to parse response body as JSON'))
          }
        },
      }
    }
  }
  return {
    default: { post: vi.fn() },
    HTTPError,
  }
})

const mockFetchAdminSiteSettings = vi.fn()
const mockUpdateAdminSiteSettings = vi.fn()
const mockFetchAdminPages = vi.fn()
const mockCreateAdminPage = vi.fn()
const mockUpdateAdminPage = vi.fn()
const mockUpdateAdminPageOrder = vi.fn()
const mockDeleteAdminPage = vi.fn()
const mockChangeAdminPassword = vi.fn()

vi.mock('@/api/admin', () => ({
  fetchAdminSiteSettings: (...args: unknown[]) => mockFetchAdminSiteSettings(...args) as unknown,
  updateAdminSiteSettings: (...args: unknown[]) => mockUpdateAdminSiteSettings(...args) as unknown,
  fetchAdminPages: (...args: unknown[]) => mockFetchAdminPages(...args) as unknown,
  createAdminPage: (...args: unknown[]) => mockCreateAdminPage(...args) as unknown,
  updateAdminPage: (...args: unknown[]) => mockUpdateAdminPage(...args) as unknown,
  updateAdminPageOrder: (...args: unknown[]) => mockUpdateAdminPageOrder(...args) as unknown,
  deleteAdminPage: (...args: unknown[]) => mockDeleteAdminPage(...args) as unknown,
  changeAdminPassword: (...args: unknown[]) => mockChangeAdminPassword(...args) as unknown,
}))

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null) => html ?? '',
}))

vi.mock('@/components/crosspost/SocialAccountsPanel', () => ({
  default: () => <div data-testid="social-accounts-panel">Social Accounts</div>,
}))

let mockUser: UserResponse | null = null
let mockIsInitialized = true

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null; isInitialized: boolean }) => unknown) =>
    selector({ user: mockUser, isInitialized: mockIsInitialized }),
}))

vi.mock('@/stores/siteStore', () => ({
  useSiteStore: { getState: () => ({ fetchConfig: vi.fn().mockResolvedValue(undefined) }) },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import AdminPage from '../AdminPage'

const { HTTPError: MockHTTPError } = await import('@/api/client')

const defaultSettings: AdminSiteSettings = {
  title: 'My Blog',
  description: 'A test blog',
  default_author: 'Admin',
  timezone: 'UTC',
}

const defaultPages: AdminPageConfig[] = [
  { id: 'timeline', title: 'Timeline', file: null, is_builtin: true, content: null },
  { id: 'labels', title: 'Labels', file: null, is_builtin: true, content: null },
  { id: 'about', title: 'About', file: 'about.md', is_builtin: false, content: '# About' },
]

function renderAdmin() {
  return render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  )
}

function setupLoadSuccess() {
  mockFetchAdminSiteSettings.mockResolvedValue(defaultSettings)
  mockFetchAdminPages.mockResolvedValue({ pages: defaultPages })
}

describe('AdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: 'Admin', is_admin: true }
    mockIsInitialized = true
  })

  // === Auth guards ===

  it('redirects to /login when unauthenticated', () => {
    mockUser = null
    renderAdmin()
    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
  })

  it('redirects to / when non-admin', () => {
    mockUser = { id: 1, username: 'user', email: 'u@t.com', display_name: null, is_admin: false }
    renderAdmin()
    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
  })

  it('returns null while initializing', () => {
    mockIsInitialized = false
    const { container } = renderAdmin()
    expect(container.innerHTML).toBe('')
  })

  // === Loading and error states ===

  it('shows spinner while loading', () => {
    mockFetchAdminSiteSettings.mockReturnValue(new Promise(() => {}))
    mockFetchAdminPages.mockReturnValue(new Promise(() => {}))
    renderAdmin()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows 401 error as session expired', async () => {
    mockFetchAdminSiteSettings.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    mockFetchAdminPages.mockResolvedValue({ pages: [] })
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows generic error on load failure', async () => {
    mockFetchAdminSiteSettings.mockRejectedValue(new Error('Network'))
    mockFetchAdminPages.mockResolvedValue({ pages: [] })
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Failed to load admin data. Please try again later.')).toBeInTheDocument()
    })
  })

  // === Site Settings ===

  it('loads and populates site settings form', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })
    expect(screen.getByLabelText('Description')).toHaveValue('A test blog')
    expect(screen.getByLabelText('Default Author')).toHaveValue('Admin')
    expect(screen.getByLabelText('Timezone')).toHaveValue('UTC')
  })

  it('validates title is required before saving site settings', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.clear(screen.getByLabelText('Title *'))
    await user.click(screen.getByRole('button', { name: /save settings/i }))

    expect(screen.getByText('Title is required.')).toBeInTheDocument()
    expect(mockUpdateAdminSiteSettings).not.toHaveBeenCalled()
  })

  it('saves site settings successfully', async () => {
    setupLoadSuccess()
    mockUpdateAdminSiteSettings.mockResolvedValue({ ...defaultSettings, title: 'New Title' })
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.clear(screen.getByLabelText('Title *'))
    await user.type(screen.getByLabelText('Title *'), 'New Title')
    await user.click(screen.getByRole('button', { name: /save settings/i }))

    await waitFor(() => {
      expect(screen.getByText('Site settings saved.')).toBeInTheDocument()
    })
  })

  it('shows error when save site settings fails', async () => {
    setupLoadSuccess()
    mockUpdateAdminSiteSettings.mockRejectedValue(new Error('fail'))
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.click(screen.getByRole('button', { name: /save settings/i }))

    await waitFor(() => {
      expect(screen.getByText('Failed to save settings. The server may be unavailable.')).toBeInTheDocument()
    })
  })

  // === Pages Management ===

  it('renders page list with reorder buttons', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })
    expect(screen.getByText('Labels')).toBeInTheDocument()
    expect(screen.getByText('About')).toBeInTheDocument()
  })

  it('shows built-in badge for built-in pages', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getAllByText('built-in')).toHaveLength(2)
    })
  })

  it('move up at top is disabled', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })
    const moveUpBtn = screen.getByLabelText('Move Timeline up')
    expect(moveUpBtn).toBeDisabled()
  })

  it('move down at bottom is disabled', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })
    const moveDownBtn = screen.getByLabelText('Move About down')
    expect(moveDownBtn).toBeDisabled()
  })

  it('reorders pages and shows Save Order button', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })

    // Move Labels up
    await user.click(screen.getByLabelText('Move Labels up'))

    // Save Order button should appear
    expect(screen.getByRole('button', { name: /save order/i })).toBeInTheDocument()
  })

  it('saves page order', async () => {
    setupLoadSuccess()
    mockUpdateAdminPageOrder.mockResolvedValue({ pages: defaultPages })
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Move Labels up'))
    await user.click(screen.getByRole('button', { name: /save order/i }))

    await waitFor(() => {
      expect(screen.getByText('Page order saved.')).toBeInTheDocument()
    })
  })

  it('expands page to show edit form', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    await user.click(screen.getByText('About'))

    await waitFor(() => {
      expect(screen.getByLabelText('Title')).toBeInTheDocument()
    })
  })

  it('shows no-changes message for unchanged page save', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    await user.click(screen.getByText('About'))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /save page/i }))

    await waitFor(() => {
      expect(screen.getByText('No changes to save.')).toBeInTheDocument()
    })
  })

  it('saves page with changed title', async () => {
    setupLoadSuccess()
    mockUpdateAdminPage.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    await user.click(screen.getByText('About'))
    await waitFor(() => {
      expect(screen.getByLabelText('Title')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'About Us')
    await user.click(screen.getByRole('button', { name: /save page/i }))

    await waitFor(() => {
      expect(screen.getByText('Page saved.')).toBeInTheDocument()
    })
    expect(mockUpdateAdminPage).toHaveBeenCalledWith('about', { title: 'About Us' })
  })

  // === Add Page ===

  it('shows add page form and creates page', async () => {
    setupLoadSuccess()
    const newPage: AdminPageConfig = {
      id: 'contact',
      title: 'Contact',
      file: 'contact.md',
      is_builtin: false,
      content: '',
    }
    mockCreateAdminPage.mockResolvedValue(newPage)
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add page/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/Page ID/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Page ID/), 'contact')
    await user.type(screen.getByPlaceholderText('e.g. About'), 'Contact')
    await user.click(screen.getByRole('button', { name: /create page/i }))

    await waitFor(() => {
      expect(screen.getByText('Page "Contact" created.')).toBeInTheDocument()
    })
  })

  it('shows 409 error for duplicate page ID', async () => {
    setupLoadSuccess()
    mockCreateAdminPage.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(409),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add page/i }))
    await user.type(screen.getByLabelText(/Page ID/), 'timeline')
    await user.type(screen.getByPlaceholderText('e.g. About'), 'Timeline 2')
    await user.click(screen.getByRole('button', { name: /create page/i }))

    await waitFor(() => {
      expect(screen.getByText('A page with ID "timeline" already exists.')).toBeInTheDocument()
    })
  })

  it('validates both ID and title are required for add page', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add page/i }))

    // Create button should be disabled when fields are empty
    expect(screen.getByRole('button', { name: /create page/i })).toBeDisabled()
  })

  // === Delete Page ===

  it('delete confirmation flow works (confirm)', async () => {
    setupLoadSuccess()
    mockDeleteAdminPage.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    // Expand page
    await user.click(screen.getByText('About'))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /delete page/i })).toBeInTheDocument()
    })

    // Click Delete Page to show confirmation
    await user.click(screen.getByRole('button', { name: /delete page/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    })

    // Confirm delete
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => {
      expect(screen.getByText('Page deleted.')).toBeInTheDocument()
    })
    expect(mockDeleteAdminPage).toHaveBeenCalledWith('about')
  })

  it('delete confirmation flow cancel', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    await user.click(screen.getByText('About'))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /delete page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /delete page/i }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /cancel/i }))

    // Confirm button should disappear
    expect(screen.queryByRole('button', { name: /confirm delete/i })).not.toBeInTheDocument()
  })

  // === Password Change ===

  it('validates all password fields are required', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    // Submit with empty fields
    await user.click(screen.getByRole('button', { name: /change password/i }))

    expect(screen.getByText('All fields are required.')).toBeInTheDocument()
  })

  it('validates passwords must match', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword1')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword2')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    expect(screen.getByText('New passwords do not match.')).toBeInTheDocument()
  })

  it('validates minimum 8 characters', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpass')
    await user.type(screen.getByLabelText(/^New Password/), 'short')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'short')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    expect(screen.getByText('New password must be at least 8 characters.')).toBeInTheDocument()
  })

  it('changes password successfully and clears fields', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword123')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword123')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Password changed successfully.')).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/Current Password/)).toHaveValue('')
    expect(screen.getByLabelText(/^New Password/)).toHaveValue('')
    expect(screen.getByLabelText(/Confirm New Password/)).toHaveValue('')
  })

  it('shows 400 error with detail from response', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number, body?: string) => Error)(
        400,
        JSON.stringify({ detail: 'Current password is incorrect.' }),
      ),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'wrongpass')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword123')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword123')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Current password is incorrect.')).toBeInTheDocument()
    })
  })

  it('shows session expired for 401 password error', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword123')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword123')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('renders Admin Panel heading', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Admin Panel')).toBeInTheDocument()
    })
  })

  it('renders social accounts panel', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByTestId('social-accounts-panel')).toBeInTheDocument()
    })
  })

  it('clears password error when user types in password field', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    // Trigger a password error
    await user.click(screen.getByRole('button', { name: /change password/i }))
    expect(screen.getByText('All fields are required.')).toBeInTheDocument()

    // Type in the current password field
    await user.type(screen.getByLabelText(/Current Password/), 'a')

    // Error should be cleared
    expect(screen.queryByText('All fields are required.')).not.toBeInTheDocument()
  })

  it('shows page ID format hint in add page form', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add page/i }))

    await waitFor(() => {
      expect(screen.getByText(/lowercase/i)).toBeInTheDocument()
    })
  })

  it('shows preview error when preview API fails', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    setupLoadSuccess()
    const user = userEvent.setup()
    const mockApi = (await import('@/api/client')).default
    vi.mocked(mockApi.post).mockReturnValue({
      json: () => Promise.reject(new Error('Server error')),
    } as ReturnType<typeof mockApi.post>)

    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('About')).toBeInTheDocument()
    })

    await user.click(screen.getByText('About'))

    await waitFor(() => {
      expect(screen.getByText('Preview unavailable')).toBeInTheDocument()
    })
  })

  it('shows password min length hint', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
    })
  })
})
