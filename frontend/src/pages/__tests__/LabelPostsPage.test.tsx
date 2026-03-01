import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, LabelResponse, PostListResponse } from '@/api/client'

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
const mockFetchLabelPosts = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabel: (...args: unknown[]) => mockFetchLabel(...args) as unknown,
  fetchLabelPosts: (...args: unknown[]) => mockFetchLabelPosts(...args) as unknown,
}))

vi.mock('@/components/posts/PostCard', () => ({
  default: ({ post }: { post: { title: string } }) => (
    <div data-testid="post-card">{post.title}</div>
  ),
}))

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

import LabelPostsPage from '../LabelPostsPage'

const { HTTPError: MockHTTPError } = await import('@/api/client')

const testLabel: LabelResponse = {
  id: 'swe',
  names: ['software engineering'],
  is_implicit: false,
  parents: ['cs'],
  children: [],
  post_count: 2,
}

const postsData: PostListResponse = {
  posts: [
    {
      id: 1, file_path: 'posts/a.md', title: 'Post A', author: 'Admin',
      created_at: '2026-02-01 12:00:00+00:00', modified_at: '2026-02-01 12:00:00+00:00',
      is_draft: false, rendered_excerpt: '<p>A</p>', labels: ['swe'],
    },
    {
      id: 2, file_path: 'posts/b.md', title: 'Post B', author: 'Admin',
      created_at: '2026-02-02 12:00:00+00:00', modified_at: '2026-02-02 12:00:00+00:00',
      is_draft: false, rendered_excerpt: '<p>B</p>', labels: ['swe'],
    },
  ],
  total: 2,
  page: 1,
  per_page: 20,
  total_pages: 1,
}

function renderPage(labelId = 'swe') {
  const router = createMemoryRouter(
    [{ path: '/labels/:labelId', element: createElement(LabelPostsPage) }],
    { initialEntries: [`/labels/${labelId}`] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('LabelPostsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
  })

  it('shows spinner while loading', () => {
    mockFetchLabel.mockReturnValue(new Promise(() => {}))
    mockFetchLabelPosts.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows 404 error', async () => {
    mockFetchLabel.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(404),
    )
    mockFetchLabelPosts.mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Label not found.')).toBeInTheDocument()
    })
  })

  it('shows 401 error', async () => {
    mockFetchLabel.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    mockFetchLabelPosts.mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows generic error', async () => {
    mockFetchLabel.mockRejectedValue(new Error('Network'))
    mockFetchLabelPosts.mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Failed to load label posts. Please try again later.')).toBeInTheDocument()
    })
  })

  it('renders label heading with names and post cards', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.getByText('software engineering')).toBeInTheDocument()
    expect(screen.getByText('Post A')).toBeInTheDocument()
    expect(screen.getByText('Post B')).toBeInTheDocument()
  })

  it('shows empty state', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabelPosts.mockResolvedValue({ ...postsData, posts: [] })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('No posts with this label.')).toBeInTheDocument()
    })
  })

  it('shows settings gear when authenticated', async () => {
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Label settings')).toBeInTheDocument()
    })
  })

  it('hides settings gear when not authenticated', async () => {
    mockUser = null
    mockFetchLabel.mockResolvedValue(testLabel)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText('Label settings')).not.toBeInTheDocument()
  })
})
