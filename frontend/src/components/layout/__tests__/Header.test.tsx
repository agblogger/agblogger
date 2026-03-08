import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, SiteConfigResponse } from '@/api/client'

const siteConfig: SiteConfigResponse = {
  title: 'My Blog',
  description: 'A test blog',
  pages: [
    { id: 'timeline', title: 'Posts', file: null },
    { id: 'labels', title: 'Labels', file: null },
  ],
}

let mockUser: UserResponse | null = null
let mockIsLoggingOut = false
const mockLogout = vi.fn()
let mockTheme: 'light' | 'dark' = 'light'
const mockToggleTheme = vi.fn()

vi.mock('@/stores/siteStore', () => ({
  useSiteStore: (selector: (s: { config: SiteConfigResponse | null }) => unknown) =>
    selector({ config: siteConfig }),
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: {
    user: UserResponse | null
    logout: () => Promise<void>
    isLoggingOut: boolean
  }) => unknown) =>
    selector({ user: mockUser, logout: mockLogout, isLoggingOut: mockIsLoggingOut }),
}))

vi.mock('@/stores/themeStore', () => ({
  useThemeStore: (selector: (s: {
    theme: 'light' | 'dark'
    toggleTheme: () => void
  }) => unknown) =>
    selector({ theme: mockTheme, toggleTheme: mockToggleTheme }),
}))

import Header from '../Header'

function renderHeader(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Header />
    </MemoryRouter>,
  )
}

describe('Header', () => {
  beforeEach(() => {
    mockUser = null
    mockIsLoggingOut = false
    mockTheme = 'light'
    vi.clearAllMocks()
  })

  it('renders site title', () => {
    renderHeader()
    expect(screen.getByText('My Blog')).toBeInTheDocument()
  })

  it('Labels active at /labels', () => {
    renderHeader('/labels')
    const labelsLink = screen.getByRole('link', { name: 'Labels' })
    expect(labelsLink.className).toContain('border-accent')
  })

  it('Labels active at /labels/swe', () => {
    renderHeader('/labels/swe')
    const labelsLink = screen.getByRole('link', { name: 'Labels' })
    expect(labelsLink.className).toContain('border-accent')
  })

  it('shows login when unauthenticated', () => {
    renderHeader()
    expect(screen.getByLabelText('Login')).toBeInTheDocument()
  })

  it('shows write and logout when authenticated', () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    renderHeader()
    expect(screen.getAllByText('Write').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByLabelText('Logout').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByLabelText('Login')).not.toBeInTheDocument()
  })

  it('disables logout button while logout is in progress', () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockIsLoggingOut = true
    renderHeader()
    const logoutButtons = screen.getAllByLabelText('Logout')
    logoutButtons.forEach((btn) => expect(btn).toBeDisabled())
  })

  it('logout button has tooltip', () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    renderHeader()
    const logoutButtons = screen.getAllByLabelText('Logout')
    // Desktop logout button has tooltip
    expect(logoutButtons.some((btn) => btn.getAttribute('title') === 'Log out')).toBe(true)
  })

  it('shows hamburger menu button', () => {
    renderHeader()
    expect(screen.getByLabelText('Menu')).toBeInTheDocument()
  })

  it('toggles mobile menu on hamburger click', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    renderHeader()

    const menuButton = screen.getByLabelText('Menu')
    await userEvent.click(menuButton)

    // Mobile menu should show nav links
    const postLinks = screen.getAllByText('Posts')
    expect(postLinks.length).toBeGreaterThanOrEqual(2) // desktop + mobile
  })

  it('opens search on click', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    expect(screen.getByPlaceholderText('Search posts...')).toBeInTheDocument()
  })

  it('closes search when close button is clicked', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    expect(screen.getByPlaceholderText('Search posts...')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Close search'))
    expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
  })

  it('shows admin link for admin user', () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    renderHeader()
    expect(screen.getAllByLabelText('Admin').length).toBeGreaterThanOrEqual(1)
  })

  it('hides admin link for non-admin user', () => {
    mockUser = { id: 1, username: 'user', email: 'u@b.com', display_name: null, is_admin: false }
    renderHeader()
    expect(screen.queryByLabelText('Admin')).not.toBeInTheDocument()
  })

  it('calls logout on logout button click', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockLogout.mockResolvedValue(undefined)
    renderHeader()

    const logoutButtons = screen.getAllByLabelText('Logout')
    await userEvent.click(logoutButtons[0]!)

    expect(mockLogout).toHaveBeenCalled()
  })

  it('Posts active at /', () => {
    renderHeader('/')
    const postsLink = screen.getByRole('link', { name: 'Posts' })
    expect(postsLink.className).toContain('border-accent')
  })

  it('mobile menu shows login for unauthenticated user', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Menu'))
    // Mobile menu should have a login link
    const loginLinks = screen.getAllByLabelText('Login')
    expect(loginLinks.length).toBeGreaterThanOrEqual(2)
  })

  it('search form submission clears and closes', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))

    const input = screen.getByPlaceholderText('Search posts...')
    await userEvent.type(input, 'test query')
    await userEvent.keyboard('{Enter}')

    // Search input should be closed after submit
    expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
  })

  it('search button has keyboard shortcut tooltip', () => {
    renderHeader()
    const searchButton = screen.getByLabelText('Search')
    expect(searchButton.getAttribute('title')).toBe('Search (/)')
  })

  it('opens search on / key press', async () => {
    renderHeader()
    await userEvent.keyboard('/')
    expect(screen.getByPlaceholderText('Search posts...')).toBeInTheDocument()
  })

  it('does not submit empty search', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))

    const input = screen.getByPlaceholderText('Search posts...')
    await userEvent.click(input)
    await userEvent.keyboard('{Enter}')

    // Search should still be open since query was empty
    expect(input).toBeInTheDocument()
  })

  it('toggles theme on theme button click', async () => {
    renderHeader()

    const themeButtons = screen.getAllByLabelText('Toggle theme')
    expect(themeButtons.length).toBeGreaterThanOrEqual(1)

    await userEvent.click(themeButtons[0]!)
    expect(mockToggleTheme).toHaveBeenCalledTimes(1)
  })

  it('shows correct theme tooltip', () => {
    mockTheme = 'dark'
    renderHeader()

    const themeButtons = screen.getAllByLabelText('Toggle theme')
    expect(themeButtons.some((btn) => btn.getAttribute('title') === 'Theme: dark')).toBe(true)
  })
})
