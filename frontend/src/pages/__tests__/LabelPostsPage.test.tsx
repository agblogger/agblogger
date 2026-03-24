import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { UserResponse, LabelResponse, PostListResponse } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
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

vi.mock('@/components/labels/LabelChip', () => ({
  default: ({ labelId }: { labelId: string }) => (
    <a data-testid="label-chip" href={`/labels/${labelId}`}>#{labelId}</a>
  ),
}))

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

import LabelPostsPage from '../LabelPostsPage'

const testLabel: LabelResponse = {
  id: 'swe',
  names: ['software engineering'],
  is_implicit: false,
  parents: [],
  children: [],
  post_count: 2,
}

const postsData: PostListResponse = {
  posts: [
    {
      id: 1, file_path: 'posts/a/index.md', title: 'Post A', author: 'Admin',
      created_at: '2026-02-01 12:00:00+00:00', modified_at: '2026-02-01 12:00:00+00:00',
      is_draft: false, rendered_excerpt: '<p>A</p>', labels: ['swe'],
    },
    {
      id: 2, file_path: 'posts/b/index.md', title: 'Post B', author: 'Admin',
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
      mockHttpError(404),
    )
    mockFetchLabelPosts.mockResolvedValue({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Label not found.')).toBeInTheDocument()
    })
  })

  it('shows 401 error', async () => {
    mockFetchLabel.mockRejectedValue(
      mockHttpError(401),
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

  it('renders children as clickable chips', async () => {
    const labelWithChildren: LabelResponse = {
      ...testLabel,
      children: ['frontend', 'backend'],
      parents: [],
    }
    mockFetchLabel.mockResolvedValue(labelWithChildren)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.getByText('Children')).toBeInTheDocument()
    const chips = screen.getAllByTestId('label-chip')
    expect(chips).toHaveLength(2)
    expect(chips[0]).toHaveAttribute('href', '/labels/frontend')
    expect(chips[1]).toHaveAttribute('href', '/labels/backend')
  })

  it('renders parents as clickable links', async () => {
    const labelWithParents: LabelResponse = {
      ...testLabel,
      children: [],
      parents: ['cs', 'engineering'],
    }
    mockFetchLabel.mockResolvedValue(labelWithParents)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.getByText('Parents')).toBeInTheDocument()
    const csLink = screen.getByRole('link', { name: '#cs' })
    expect(csLink).toHaveAttribute('href', '/labels/cs')
    const engLink = screen.getByRole('link', { name: '#engineering' })
    expect(engLink).toHaveAttribute('href', '/labels/engineering')
  })

  it('renders both children and parents with children first', async () => {
    const labelWithBoth: LabelResponse = {
      ...testLabel,
      children: ['frontend'],
      parents: ['cs'],
    }
    mockFetchLabel.mockResolvedValue(labelWithBoth)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    const childrenHeading = screen.getByText('Children')
    const parentsHeading = screen.getByText('Parents')
    // Children section appears before Parents in the DOM
    expect(
      childrenHeading.compareDocumentPosition(parentsHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('renders no hierarchy sections when label has no parents or children', async () => {
    const labelNoHierarchy: LabelResponse = {
      ...testLabel,
      children: [],
      parents: [],
    }
    mockFetchLabel.mockResolvedValue(labelNoHierarchy)
    mockFetchLabelPosts.mockResolvedValue(postsData)
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.queryByText('Children')).not.toBeInTheDocument()
    expect(screen.queryByText('Parents')).not.toBeInTheDocument()
  })
})
