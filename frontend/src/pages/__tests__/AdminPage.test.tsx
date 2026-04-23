import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { SWRConfig } from 'swr'

import type { UserResponse, AdminSiteSettings, AdminPageConfig } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: { post: vi.fn() },
    HTTPError: MockHTTPError,
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

vi.mock('@/components/admin/AnalyticsPanel', () => ({
  default: () => <div data-testid="analytics-panel">Analytics</div>,
}))

const mockUpdateProfile = vi.fn()

vi.mock('@/api/auth', () => ({
  updateProfile: (...args: unknown[]) => mockUpdateProfile(...args) as unknown,
}))

let mockUser: UserResponse | null = null
let mockIsInitialized = true
const mockSetUser = vi.fn()
const mockLogout = vi.fn()

vi.mock('@/stores/authStore', () => ({
  useAuthStore: Object.assign(
    (selector: (s: { user: UserResponse | null; isInitialized: boolean; setUser: typeof mockSetUser }) => unknown) =>
      selector({ user: mockUser, isInitialized: mockIsInitialized, setUser: mockSetUser }),
    { getState: () => ({ logout: mockLogout }) },
  ),
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
import api from '@/api/client'

const mockApiPost = vi.mocked(api.post)

const defaultSettings: AdminSiteSettings = {
  title: 'My Blog',
  description: 'A test blog',
  timezone: 'UTC',
  password_change_disabled: false,
  favicon: null,
}

const defaultPages: AdminPageConfig[] = [
  { id: 'timeline', title: 'Timeline', file: null, is_builtin: true, content: null },
  { id: 'labels', title: 'Labels', file: null, is_builtin: true, content: null },
  { id: 'about', title: 'About', file: 'about.md', is_builtin: false, content: '# About' },
]

function renderAdmin(path = '/admin') {
  const router = createMemoryRouter(
    [{ path: '/admin', element: createElement(AdminPage) }],
    { initialEntries: [path] },
  )
  return render(
    createElement(
      SWRConfig,
      { value: { provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false, revalidateOnFocus: false, revalidateOnReconnect: false, onError: () => {} } },
      createElement(RouterProvider, { router }),
    ),
  )
}

function setupLoadSuccess() {
  mockFetchAdminSiteSettings.mockResolvedValue(defaultSettings)
  mockFetchAdminPages.mockResolvedValue({ pages: defaultPages })
  mockApiPost.mockReturnValue({
    json: () => Promise.resolve({ html: '<p>Preview</p>' }),
  } as ReturnType<typeof api.post>)
}

async function switchToTab(user: ReturnType<typeof userEvent.setup>, tabName: string) {
  const btn = screen.getByRole('button', { name: tabName })
  await user.click(btn)
}

describe('AdminPage', () => {
  // Mock Intl.supportedValuesOf for TimezoneCombobox
  const originalIntl = globalThis.Intl
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.Intl = {
      ...originalIntl,
      supportedValuesOf: vi.fn().mockReturnValue(['America/New_York', 'Europe/London', 'Asia/Tokyo', 'UTC']),
      DateTimeFormat: class extends originalIntl.DateTimeFormat {
        override resolvedOptions() {
          return { ...super.resolvedOptions(), timeZone: 'America/New_York' }
        }
      },
    } as unknown as typeof Intl
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: 'Admin' }
    mockIsInitialized = true
  })
  afterEach(() => {
    globalThis.Intl = originalIntl
  })

  // === Auth guards ===

  it('redirects to /login when unauthenticated', () => {
    mockUser = null
    renderAdmin()
    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
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
      mockHttpError(401),
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
    expect(screen.getByLabelText('Timezone')).toHaveValue('UTC')
  })

  it('opens the social tab directly from the tab query parameter', async () => {
    setupLoadSuccess()
    renderAdmin('/admin?tab=social')

    await waitFor(() => {
      expect(screen.getByTestId('social-accounts-panel')).toBeInTheDocument()
    })
  })

  it('falls back to settings tab for invalid tab query parameter', async () => {
    setupLoadSuccess()
    renderAdmin('/admin?tab=bogus')

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })
    // Settings tab should be active, not any other tab content
    expect(screen.queryByTestId('social-accounts-panel')).not.toBeInTheDocument()
  })

  it('syncs active tab when URL search parameter changes', async () => {
    setupLoadSuccess()
    const { unmount } = renderAdmin('/admin?tab=settings')

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })
    unmount()

    // Re-render with social tab — should switch to social
    renderAdmin('/admin?tab=social')
    await waitFor(() => {
      expect(screen.getByTestId('social-accounts-panel')).toBeInTheDocument()
    })
  })

  it('does not display the default author field', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    expect(screen.queryByLabelText('Default author')).not.toBeInTheDocument()
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
      expect(screen.getByText('Settings saved.')).toBeInTheDocument()
    })
  })

  it('keeps saved site settings after switching tabs', async () => {
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
      expect(screen.getByText('Settings saved.')).toBeInTheDocument()
    })

    await switchToTab(user, 'Pages')
    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })

    await switchToTab(user, 'Settings')
    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('New Title')
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
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })
    expect(screen.getByText('Labels')).toBeInTheDocument()
    expect(screen.getByText('About')).toBeInTheDocument()
  })

  it('shows built-in badge for built-in pages', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

    await waitFor(() => {
      expect(screen.getAllByText('built-in')).toHaveLength(2)
    })
  })

  it('move up at top is disabled', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })
    const moveUpBtn = screen.getByLabelText('Move Timeline up')
    expect(moveUpBtn).toBeDisabled()
  })

  it('move down at bottom is disabled', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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

  it('keeps created pages after switching tabs', async () => {
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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add page/i }))
    await user.type(screen.getByLabelText(/Page ID/), 'contact')
    await user.type(screen.getByPlaceholderText('e.g. About'), 'Contact')
    await user.click(screen.getByRole('button', { name: /create page/i }))

    await waitFor(() => {
      expect(screen.getByText('Page "Contact" created.')).toBeInTheDocument()
    })
    expect(screen.getByText('Contact')).toBeInTheDocument()

    await switchToTab(user, 'Settings')
    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toBeInTheDocument()
    })

    await switchToTab(user, 'Pages')
    await waitFor(() => {
      expect(screen.getByText('Contact')).toBeInTheDocument()
    })
  })

  it('shows 409 error for duplicate page ID', async () => {
    setupLoadSuccess()
    mockCreateAdminPage.mockRejectedValue(
      mockHttpError(409),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

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
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

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
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

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
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword1234')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword1234')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Password changed successfully.')).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/Current Password/)).toHaveValue('')
    expect(screen.getByLabelText(/^New Password/)).toHaveValue('')
    expect(screen.getByLabelText(/Confirm New Password/)).toHaveValue('')
  })

  it('accepts an 8-character password', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'exactly8')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'exactly8')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(mockChangeAdminPassword).toHaveBeenCalledWith({
        current_password: 'oldpassword',
        new_password: 'exactly8',
        confirm_password: 'exactly8',
      })
    })
    expect(
      screen.queryByText('New password must be at least 8 characters.'),
    ).not.toBeInTheDocument()
  })

  it('shows 400 error with detail from response', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockRejectedValue(
      mockHttpError(400, JSON.stringify({ detail: 'Current password is incorrect.' })),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'wrongpass')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword1234')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword1234')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Current password is incorrect.')).toBeInTheDocument()
    })
  })

  it('shows session expired for 401 password error', async () => {
    setupLoadSuccess()
    mockChangeAdminPassword.mockRejectedValue(
      mockHttpError(401),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Current Password/), 'oldpassword')
    await user.type(screen.getByLabelText(/^New Password/), 'newpassword1234')
    await user.type(screen.getByLabelText(/Confirm New Password/), 'newpassword1234')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  // === Password Change Disabled ===

  it('hides password form when password change is disabled', async () => {
    mockFetchAdminSiteSettings.mockResolvedValue({
      ...defaultSettings,
      password_change_disabled: true,
    })
    mockFetchAdminPages.mockResolvedValue({ pages: defaultPages })
    renderAdmin()
    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(
        screen.getByText('Password changes are disabled by server configuration.'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument()
  })

  it('shows password form when password change is enabled', async () => {
    setupLoadSuccess()
    renderAdmin()
    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText(/current password/i)).toBeInTheDocument()
    })
    expect(
      screen.queryByText('Password changes are disabled by server configuration.'),
    ).not.toBeInTheDocument()
  })

  // === Profile Update ===

  it('saves profile successfully', async () => {
    setupLoadSuccess()
    mockUpdateProfile.mockResolvedValue({
      id: 1,
      username: 'admin',
      email: 'a@t.com',
      display_name: 'New Display Name',
    })
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Display Name'))
    await user.type(screen.getByLabelText('Display Name'), 'New Display Name')
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => {
      expect(screen.getByText('Profile updated successfully.')).toBeInTheDocument()
    })
    expect(mockUpdateProfile).toHaveBeenCalledWith({ display_name: 'New Display Name' })
    expect(mockSetUser).toHaveBeenCalledWith({
      id: 1,
      username: 'admin',
      email: 'a@t.com',
      display_name: 'New Display Name',
    })
  })

  it('shows username is required error', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    // Changing username makes Save Profile enabled, so we can click it
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    expect(screen.getByText('Username is required.')).toBeInTheDocument()
  })

  it('shows username already taken error (409)', async () => {
    setupLoadSuccess()
    mockUpdateProfile.mockRejectedValue(
      mockHttpError(409),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    await user.type(screen.getByLabelText('Username'), 'taken-user')
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => {
      expect(screen.getByText('Username is already taken.')).toBeInTheDocument()
    })
  })

  it('shows validation error (422)', async () => {
    setupLoadSuccess()
    mockUpdateProfile.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: 'Invalid format' })),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    await user.type(screen.getByLabelText('Username'), 'bad!user')
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid format')).toBeInTheDocument()
    })
  })

  it('shows session expired error (401)', async () => {
    setupLoadSuccess()
    mockUpdateProfile.mockRejectedValue(
      mockHttpError(401),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    await user.type(screen.getByLabelText('Username'), 'newname')
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows network error', async () => {
    setupLoadSuccess()
    mockUpdateProfile.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    await user.clear(screen.getByLabelText('Username'))
    await user.type(screen.getByLabelText('Username'), 'newname')
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to update profile. The server may be unavailable.'),
      ).toBeInTheDocument()
    })
  })

  it('disables Save Profile when no changes', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: /save profile/i })).toBeDisabled()
  })

  it('clears profile error when user types', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByLabelText('Username')).toBeInTheDocument()
    })

    // Clear the username to trigger "Username is required." error
    await user.clear(screen.getByLabelText('Username'))
    await user.click(screen.getByRole('button', { name: /save profile/i }))

    expect(screen.getByText('Username is required.')).toBeInTheDocument()

    // Type in the username field
    await user.type(screen.getByLabelText('Username'), 'a')

    // Error should be cleared
    expect(screen.queryByText('Username is required.')).not.toBeInTheDocument()
  })

  it('renders Admin Panel heading', async () => {
    setupLoadSuccess()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByText('Admin Panel')).toBeInTheDocument()
    })
  })

  // === Tab Navigation ===

  it('switches between admin tabs', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    // Default tab shows settings
    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toBeInTheDocument()
    })

    // Switch to Pages tab
    await switchToTab(user, 'Pages')
    expect(screen.queryByLabelText('Title *')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Timeline')).toBeInTheDocument()
    })

    // Switch to Password tab
    await switchToTab(user, 'Account')
    expect(screen.queryByText('Timeline')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByLabelText(/Current Password/)).toBeInTheDocument()
    })

    // Switch back to Settings
    await switchToTab(user, 'Settings')
    expect(screen.queryByLabelText(/Current Password/)).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toBeInTheDocument()
    })
  })

  it('blocks tab changes while a mutation is pending', async () => {
    setupLoadSuccess()
    let resolveSave: ((value: AdminSiteSettings) => void) | undefined
    mockUpdateAdminSiteSettings.mockReturnValue(
      new Promise<AdminSiteSettings>((resolve) => {
        resolveSave = resolve
      }),
    )
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
    })

    await user.clear(screen.getByLabelText('Title *'))
    await user.type(screen.getByLabelText('Title *'), 'New Title')
    await user.click(screen.getByRole('button', { name: /save settings/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeDisabled()
    })

    await switchToTab(user, 'Pages')
    expect(screen.getByLabelText('Title *')).toBeInTheDocument()
    expect(screen.queryByText('Timeline')).not.toBeInTheDocument()

    resolveSave?.({ ...defaultSettings, title: 'New Title' })

    await waitFor(() => {
      expect(screen.getByText('Settings saved.')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pages' })).toBeEnabled()
    })
  })

  it('renders social accounts panel', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Social' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Social')

    await waitFor(() => {
      expect(screen.getByTestId('social-accounts-panel')).toBeInTheDocument()
    })
  })

  it('renders analytics tab', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Analytics' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Analytics')

    await waitFor(() => {
      expect(screen.getByTestId('analytics-panel')).toBeInTheDocument()
    })
  })

  it('opens the analytics tab directly from the tab query parameter', async () => {
    setupLoadSuccess()
    renderAdmin('/admin?tab=analytics')

    await waitFor(() => {
      expect(screen.getByTestId('analytics-panel')).toBeInTheDocument()
    })
  })

  it('clears password error when user types in password field', async () => {
    setupLoadSuccess()
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
      expect(screen.getByRole('button', { name: 'Pages' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Pages')

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
    const user = userEvent.setup()
    renderAdmin()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
    })
    await switchToTab(user, 'Account')

    await waitFor(() => {
      expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
    })
  })

  // === Unsaved Changes ===

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

    it('add page draft fields trigger dirty state', async () => {
      setupLoadSuccess()
      const user = userEvent.setup()
      renderAdmin()

      await waitFor(() => {
        expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
      })

      await user.click(screen.getByRole('button', { name: 'Pages' }))

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: /add page/i }))
      await user.type(screen.getByLabelText(/Page ID/), 'contact')
      await user.type(screen.getByPlaceholderText('e.g. About'), 'Contact')

      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      await user.click(screen.getByRole('button', { name: 'Settings' }))

      expect(confirmSpy).toHaveBeenCalledWith(
        'You have unsaved changes. Are you sure you want to leave?',
      )
      expect(screen.getByLabelText(/Page ID/)).toBeInTheDocument()
      confirmSpy.mockRestore()
    })

    it('dirty flags are reset after confirming tab switch so subsequent switches do not re-prompt', async () => {
      setupLoadSuccess()
      const user = userEvent.setup()
      renderAdmin()

      await waitFor(() => {
        expect(screen.getByLabelText('Title *')).toHaveValue('My Blog')
      })

      // Make the Settings tab dirty
      await user.clear(screen.getByLabelText('Title *'))
      await user.type(screen.getByLabelText('Title *'), 'Dirty Title')

      // Confirm the tab switch to Social (which has no dirty-reporting section,
      // so the unmount cleanup from SiteSettingsSection would normally reset siteDirty,
      // but the explicit reset in handleTabSwitch ensures the flags are cleared immediately)
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      await user.click(screen.getByRole('button', { name: 'Social' }))

      expect(confirmSpy).toHaveBeenCalledOnce()
      await waitFor(() => {
        expect(screen.getByTestId('social-accounts-panel')).toBeInTheDocument()
      })

      // Now switch from Social → Account: since dirty flags were reset when confirming
      // the previous switch, this should NOT prompt again
      confirmSpy.mockClear()
      await user.click(screen.getByRole('button', { name: 'Account' }))
      expect(confirmSpy).not.toHaveBeenCalled()

      confirmSpy.mockRestore()
    })
  })
})
