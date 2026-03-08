import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

const mockFetchConfig = vi.fn()
const mockCheckAuth = vi.fn()

const siteState = {
  config: { title: 'Test Blog', description: '', pages: [{ id: 'timeline', title: 'Posts', file: null }] },
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
  useThemeStore: (selector: (s: { theme: string; toggleTheme: () => void; init: () => void }) => unknown) =>
    selector({ theme: 'light', toggleTheme: vi.fn(), init: vi.fn() }),
}))

vi.mock('@/api/posts', () => ({
  fetchPosts: vi.fn().mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 1 }),
}))

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn().mockResolvedValue([]),
}))

import App from './App'

describe('App', () => {
  it('renders the header with site title', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Test Blog')).toBeInTheDocument()
    })
  })
})
