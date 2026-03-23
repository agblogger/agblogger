import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetchConfig = vi.fn()
const mockCheckAuth = vi.fn()

const siteState = {
  config: { title: 'Test Blog', description: '', pages: [{ id: 'timeline', title: 'Posts', file: null }] } as { title: string; description: string; pages: { id: string; title: string; file: null }[] } | null,
  isLoading: false,
  fetchConfig: mockFetchConfig,
}

const authState = {
  user: null,
  isLoading: false,
  isLoggingOut: false,
  error: null,
  login: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
  checkAuth: mockCheckAuth,
}

vi.mock('@/stores/siteStore', () => ({
  useSiteStore: (selector: (s: typeof siteState) => unknown) => selector(siteState),
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: typeof authState) => unknown) => selector(authState),
}))

vi.mock('@/stores/themeStore', () => ({
  useThemeStore: (selector: (s: { theme: string; toggleTheme: () => void; init: () => () => void }) => unknown) =>
    selector({ theme: 'light', toggleTheme: vi.fn(), init: () => () => {} }),
}))

vi.mock('@/api/posts', () => ({
  fetchPosts: vi.fn().mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 1 }),
}))

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn().mockResolvedValue([]),
}))

import App from './App'

describe('App', () => {
  beforeEach(() => {
    siteState.config = { title: 'Test Blog', description: '', pages: [{ id: 'timeline', title: 'Posts', file: null }] }
    document.title = 'Blog'
  })

  it('renders the header with site title', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Test Blog')).toBeInTheDocument()
    })
  })

  describe('document.title', () => {
    it('sets document.title from site config when title is present', async () => {
      siteState.config = { title: 'My Awesome Blog', description: '', pages: [] }
      render(<App />)
      await waitFor(() => {
        expect(document.title).toBe('My Awesome Blog')
      })
    })

    it('leaves document.title as default "Blog" when config title is empty', async () => {
      siteState.config = { title: '', description: '', pages: [] }
      render(<App />)
      // Give effects time to run; title must remain unchanged
      await waitFor(() => {
        expect(screen.getByRole('main')).toBeInTheDocument()
      })
      expect(document.title).toBe('Blog')
    })

    it('leaves document.title as default "Blog" when config is null', async () => {
      siteState.config = null
      render(<App />)
      await waitFor(() => {
        expect(screen.getByRole('main')).toBeInTheDocument()
      })
      expect(document.title).toBe('Blog')
    })
  })
})
