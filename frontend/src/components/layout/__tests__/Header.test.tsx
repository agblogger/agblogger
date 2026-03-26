import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import type { UserResponse, SiteConfigResponse, SearchResult } from '@/api/client'

const mockSearchPosts = vi.fn<(q: string, limit?: number, signal?: AbortSignal) => Promise<SearchResult[]>>()

vi.mock('@/api/posts', () => ({
  searchPosts: (...args: [string, number?, AbortSignal?]) => mockSearchPosts(...args),
}))

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
let mockPanelState = 'closed'
let mockActiveFilterCount = 0
const mockTogglePanel = vi.fn()

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

vi.mock('@/stores/filterPanelStore', () => ({
  useFilterPanelStore: (selector: (s: {
    panelState: string
    activeFilterCount: number
    togglePanel: () => void
  }) => unknown) =>
    selector({
      panelState: mockPanelState,
      activeFilterCount: mockActiveFilterCount,
      togglePanel: mockTogglePanel,
    }),
}))

import Header from '../Header'

function LocationDisplay() {
  const location = useLocation()
  return <div data-testid="location-display">{location.pathname}{location.search}</div>
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function renderHeader(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Header />
      <LocationDisplay />
    </MemoryRouter>,
  )
}

describe('Header', () => {
  beforeEach(() => {
    mockUser = null
    mockIsLoggingOut = false
    mockTheme = 'light'
    mockPanelState = 'closed'
    mockActiveFilterCount = 0
    vi.clearAllMocks()
    mockSearchPosts.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
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

  it('shows filter icon on timeline page', () => {
    renderHeader('/')
    expect(screen.getByLabelText('Toggle filters')).toBeInTheDocument()
  })

  it('hides filter icon on non-timeline pages', () => {
    renderHeader('/labels')
    expect(screen.queryByLabelText('Toggle filters')).not.toBeInTheDocument()
  })

  it('hides filter icon on search page', () => {
    renderHeader('/search')
    expect(screen.queryByLabelText('Toggle filters')).not.toBeInTheDocument()
  })

  it('shows active filter count badge', () => {
    mockActiveFilterCount = 3
    renderHeader('/')
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('does not show badge when no active filters', () => {
    mockActiveFilterCount = 0
    renderHeader('/')
    // Filter button exists but no badge
    expect(screen.getByLabelText('Toggle filters')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('calls togglePanel when filter icon is clicked', async () => {
    renderHeader('/')
    await userEvent.click(screen.getByLabelText('Toggle filters'))
    expect(mockTogglePanel).toHaveBeenCalledTimes(1)
  })

  it('filter icon has active style when panel is open', () => {
    mockPanelState = 'open'
    renderHeader('/')
    const btn = screen.getByLabelText('Toggle filters')
    expect(btn.className).toContain('text-accent')
  })

  describe('live search dropdown', () => {
    const results: SearchResult[] = [
      { id: 1, file_path: 'posts/hello/index.md', title: 'Hello World', subtitle: null, rendered_excerpt: null, created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
      { id: 2, file_path: 'posts/react/index.md', title: 'React Guide', subtitle: null, rendered_excerpt: null, created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
    ]

    it('shows dropdown after typing 2+ chars with debounce', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'he')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })
      expect(mockSearchPosts).toHaveBeenCalledWith('he', 5, expect.any(AbortSignal))
    })

    it('does not search with fewer than 2 chars', async () => {
      vi.useFakeTimers()
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      fireEvent.change(screen.getByPlaceholderText('Search posts...'), { target: { value: 'h' } })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
      expect(mockSearchPosts).not.toHaveBeenCalled()
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('navigates to post on result click', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      const options = screen.getAllByRole('option')
      fireEvent.mouseDown(options[0]!)

      await waitFor(() => {
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      })
      expect(screen.getByTestId('location-display')).toHaveTextContent('/post/hello')
    })

    it('Enter with no highlight goes to search page', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{Enter}')
      expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
    })

    it('arrow down highlights first result, enter navigates to it', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{ArrowDown}')
      const options = screen.getAllByRole('option')
      expect(options[0]).toHaveAttribute('aria-selected', 'true')

      await userEvent.keyboard('{Enter}')
      expect(screen.getByTestId('location-display')).toHaveTextContent('/post/hello')
    })

    it('arrow down past last result wraps to no selection', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
      const options = screen.getAllByRole('option')
      options.forEach((opt) => expect(opt).toHaveAttribute('aria-selected', 'false'))
    })

    it('ESC closes dropdown', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('second ESC closes search entirely', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      // First ESC closes dropdown
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(screen.getByPlaceholderText('Search posts...')).toBeInTheDocument()

      // Second ESC closes search entirely
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
    })

    it('clears dropdown when input is cleared', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')
      await userEvent.type(input, 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.clear(input)
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('arrow up from first result wraps to no selection', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{ArrowDown}{ArrowUp}')
      const options = screen.getAllByRole('option')
      options.forEach((opt) => expect(opt).toHaveAttribute('aria-selected', 'false'))
    })

    it('footer click navigates to search page', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      const footer = screen.getByText('View all results')
      fireEvent.mouseDown(footer)

      await waitFor(() => {
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      })
      expect(screen.getByTestId('location-display')).toHaveTextContent('/search?q=hello')
    })

    it('shows error message in dropdown on API error', async () => {
      vi.useFakeTimers()
      mockSearchPosts.mockRejectedValue(new Error('fail'))
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      fireEvent.change(screen.getByPlaceholderText('Search posts...'), { target: { value: 'hello' } })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(screen.getByText('Search failed')).toBeInTheDocument()
      consoleSpy.mockRestore()
    })

    it('silently ignores AbortError without logging', async () => {
      vi.useFakeTimers()
      const abortError = new DOMException('The operation was aborted', 'AbortError')
      mockSearchPosts.mockRejectedValue(abortError)
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      fireEvent.change(screen.getByPlaceholderText('Search posts...'), { target: { value: 'hello' } })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(consoleSpy).not.toHaveBeenCalled()
      consoleSpy.mockRestore()
    })

    it('shows loading indicator while search is in progress', async () => {
      vi.useFakeTimers()
      const deferred = createDeferred<SearchResult[]>()
      mockSearchPosts.mockReturnValue(deferred.promise)
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      fireEvent.change(screen.getByPlaceholderText('Search posts...'), { target: { value: 'hello' } })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
      })
      expect(screen.getByText('Searching...')).toBeInTheDocument()

      await act(async () => {
        deferred.resolve([
          { id: 1, file_path: 'posts/hello/index.md', title: 'Hello World', subtitle: null, rendered_excerpt: null, created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
        ])
        await Promise.resolve()
      })
      expect(screen.queryByText('Searching...')).not.toBeInTheDocument()
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    it('dismisses dropdown but keeps search on blur when query has text', async () => {
      mockSearchPosts.mockResolvedValue(results)
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      fireEvent.blur(screen.getByPlaceholderText('Search posts...'))
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
      expect(screen.getByPlaceholderText('Search posts...')).toBeInTheDocument()
    })

    it('closes search entirely on blur when query is empty', async () => {
      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')
      expect(input).toBeInTheDocument()

      fireEvent.blur(input)
      expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
    })

    it('does not reopen dropdown after Escape dismisses it during a newer search', async () => {
      vi.useFakeTimers()
      const nextSearch = createDeferred<SearchResult[]>()
      mockSearchPosts.mockResolvedValueOnce(results).mockReturnValueOnce(nextSearch.promise)

      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')

      fireEvent.change(input, { target: { value: 'he' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
        await Promise.resolve()
      })
      expect(screen.getByRole('listbox')).toBeInTheDocument()

      fireEvent.change(input, { target: { value: 'hel' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
      })
      expect(mockSearchPosts).toHaveBeenLastCalledWith('hel', 5, expect.any(AbortSignal))

      fireEvent.keyDown(input, { key: 'Escape' })
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

      await act(async () => {
        nextSearch.resolve(results)
        await Promise.resolve()
      })

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('clears stale results when reopening dropdown after ESC', async () => {
      vi.useFakeTimers()
      mockSearchPosts.mockResolvedValueOnce(results)
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')

      // First search returns results
      fireEvent.change(input, { target: { value: 'hello' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
        await Promise.resolve()
      })
      expect(screen.getByRole('listbox')).toBeInTheDocument()

      // ESC dismisses dropdown
      fireEvent.keyDown(input, { key: 'Escape' })
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

      // Type again — dropdown reopens, should show "Searching..." not stale results
      const deferred = createDeferred<SearchResult[]>()
      mockSearchPosts.mockReturnValueOnce(deferred.promise)
      fireEvent.change(input, { target: { value: 'world' } })

      expect(screen.getByText('Searching...')).toBeInTheDocument()
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })

    it('clears stale error banner when typing after a search failure', async () => {
      vi.useFakeTimers()
      mockSearchPosts.mockRejectedValueOnce(new Error('fail'))
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      renderHeader()
      fireEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')

      // First search fails
      fireEvent.change(input, { target: { value: 'hello' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(screen.getByText('Search failed')).toBeInTheDocument()

      // Type again — error should be cleared immediately
      const deferred = createDeferred<SearchResult[]>()
      mockSearchPosts.mockReturnValueOnce(deferred.promise)
      fireEvent.change(input, { target: { value: 'world' } })
      expect(screen.queryByText('Search failed')).not.toBeInTheDocument()
      expect(screen.getByText('Searching...')).toBeInTheDocument()

      consoleSpy.mockRestore()
    })

    it('submits the edited query instead of navigating to a stale highlighted result', async () => {
      mockSearchPosts.mockResolvedValue(results)

      renderHeader()
      await userEvent.click(screen.getByLabelText('Search'))
      const input = screen.getByPlaceholderText('Search posts...')

      await userEvent.type(input, 'hello')
      await waitFor(() => {
        expect(screen.getByRole('listbox')).toBeInTheDocument()
      })

      await userEvent.keyboard('{ArrowDown}')
      expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')

      await userEvent.type(input, 'z')
      await userEvent.keyboard('{Enter}')

      expect(screen.getByTestId('location-display')).toHaveTextContent('/search?q=helloz')
    })
  })
})
