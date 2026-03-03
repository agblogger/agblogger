import { createElement } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPosts, uploadPost } from '@/api/posts'
import type { PostListResponse, UserResponse } from '@/api/client'
import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/posts', () => ({
  fetchPosts: vi.fn(),
  uploadPost: vi.fn(),
}))

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
})

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import TimelinePage from '../TimelinePage'

const mockFetchPosts = vi.mocked(fetchPosts)
const mockUploadPost = vi.mocked(uploadPost)

const postsResponse: PostListResponse = {
  posts: [
    {
      id: 1,
      file_path: 'posts/hello.md',
      title: 'Hello World',
      author: 'Admin',
      created_at: '2026-02-01 12:00:00+00:00',
      modified_at: '2026-02-01 12:00:00+00:00',
      is_draft: false,
      rendered_excerpt: '<p>First post</p>',
      labels: [],
    },
    {
      id: 2,
      file_path: 'posts/second.md',
      title: 'Second Post',
      author: 'Admin',
      created_at: '2026-02-02 12:00:00+00:00',
      modified_at: '2026-02-02 12:00:00+00:00',
      is_draft: false,
      rendered_excerpt: '<p>Another post</p>',
      labels: [],
    },
  ],
  total: 2,
  page: 1,
  per_page: 10,
  total_pages: 1,
}

const paginatedResponse: PostListResponse = {
  ...postsResponse,
  total: 30,
  total_pages: 3,
}

async function simulateFileUpload(file: File) {
  const fileInput = document.querySelector<HTMLInputElement>('input[type="file"][accept=".md,.markdown"]')
  if (!fileInput) throw new Error('File input not found — is the upload UI rendered?')
  Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
  await act(async () => {
    fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    await Promise.resolve()
  })
}

function renderTimeline(initialEntry = '/') {
  const router = createMemoryRouter(
    [{ path: '/', element: createElement(TimelinePage) }],
    { initialEntries: [initialEntry] },
  )
  return render(createElement(RouterProvider, { router }))
}

describe('TimelinePage', () => {
  beforeEach(() => {
    mockFetchPosts.mockReset()
    mockUploadPost.mockReset()
    mockNavigate.mockReset()
    mockUser = null
  })

  it('shows skeleton cards during loading', async () => {
    mockFetchPosts.mockReturnValue(new Promise(() => {})) // never resolves
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByRole('status')).toBeInTheDocument()
    })
  })

  it('renders posts', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.getByText('Second Post')).toBeInTheDocument()
  })

  it('error shows retry button', async () => {
    mockFetchPosts.mockRejectedValue(new Error('Network error'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Failed to load posts. Please try again.')).toBeInTheDocument()
    })
    expect(screen.getByText('Retry')).toBeInTheDocument()
    consoleSpy.mockRestore()
  })

  it('retry re-fetches posts', async () => {
    mockFetchPosts.mockRejectedValueOnce(new Error('Network error'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Retry')).toBeInTheDocument()
    })

    mockFetchPosts.mockResolvedValue(postsResponse)
    await userEvent.click(screen.getByText('Retry'))

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(mockFetchPosts).toHaveBeenCalledTimes(2)
    consoleSpy.mockRestore()
  })

  it('logs error to console on failure', async () => {
    const error = new Error('Network error')
    mockFetchPosts.mockRejectedValue(error)
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderTimeline()

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to fetch posts:', error)
    })
    consoleSpy.mockRestore()
  })

  it('shows empty results message for unauthenticated user', async () => {
    mockFetchPosts.mockResolvedValue({ ...postsResponse, posts: [], total: 0 })
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('No posts yet')).toBeInTheDocument()
    })
    expect(screen.getByText('Check back soon.')).toBeInTheDocument()
    expect(screen.queryByText('Write your first post')).not.toBeInTheDocument()
  })

  it('shows "Write your first post" CTA for authenticated user with no posts', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue({ ...postsResponse, posts: [], total: 0 })
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('No posts yet')).toBeInTheDocument()
    })
    const cta = screen.getByRole('link', { name: 'Write your first post' })
    expect(cta).toBeInTheDocument()
    expect(cta).toHaveAttribute('href', '/editor/new')
  })

  // === Pagination ===

  it('shows pagination when total_pages > 1', async () => {
    mockFetchPosts.mockResolvedValue(paginatedResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('1 / 3')).toBeInTheDocument()
    })
  })

  it('does not show pagination when total_pages is 1', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.queryByText('1 / 1')).not.toBeInTheDocument()
  })

  // === Upload buttons ===

  it('shows upload buttons when authenticated', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })
    expect(screen.getByText('Upload folder')).toBeInTheDocument()
  })

  it('hides upload buttons when not authenticated', async () => {
    mockUser = null
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.queryByText('Upload file')).not.toBeInTheDocument()
  })

  // === Empty state with filters ===

  it('shows "Clear filters" button when empty with active filters', async () => {
    mockFetchPosts.mockResolvedValue({ ...postsResponse, posts: [], total: 0 })
    renderTimeline('/?labels=swe')

    await waitFor(() => {
      expect(screen.getByText('No posts found')).toBeInTheDocument()
    })
    expect(screen.getByText('Try adjusting your filters.')).toBeInTheDocument()
    expect(screen.getByText('Clear filters')).toBeInTheDocument()
  })

  it('shows "Check back soon" for unauthenticated user without filters', async () => {
    mockFetchPosts.mockResolvedValue({ ...postsResponse, posts: [], total: 0 })
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Check back soon.')).toBeInTheDocument()
    })
  })

  // === Upload functionality ===

  it('successful upload navigates to post', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockResolvedValue({
      id: 3, file_path: 'posts/uploaded.md', title: 'Uploaded',
      author: 'Admin', created_at: '2026-02-22', modified_at: '2026-02-22',
      is_draft: false, rendered_excerpt: '', rendered_html: '', content: '', labels: [],
    })
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    // Simulate file input change
    const file = new File(['# Test'], 'test.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(mockUploadPost).toHaveBeenCalledWith([file])
    })

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/post/posts/uploaded.md')
    })
  })

  it('shows 413 error for large file upload', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(413),
    )
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['big'], 'big.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('File too large. Maximum size is 10 MB per file.')).toBeInTheDocument()
    })
  })

  it('shows title prompt for 422 no_title error', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number, body?: string) => Error)(
        422, JSON.stringify({ detail: 'no_title' }),
      ),
    )
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['no title'], 'notitle.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('Enter post title')).toBeInTheDocument()
    })
  })

  it('submits title prompt and uploads', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost
      .mockRejectedValueOnce(
        new (MockHTTPError as unknown as new (s: number, body?: string) => Error)(
          422, JSON.stringify({ detail: 'no_title' }),
        ),
      )
      .mockResolvedValueOnce({
        id: 3, file_path: 'posts/titled.md', title: 'My Title',
        author: 'Admin', created_at: '2026-02-22', modified_at: '2026-02-22',
        is_draft: false, rendered_excerpt: '', rendered_html: '', content: '', labels: [],
      })
    const user = userEvent.setup()
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['no title'], 'notitle.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('Enter post title')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Post title'), 'My Title')
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    await waitFor(() => {
      expect(mockUploadPost).toHaveBeenCalledWith([file], 'My Title')
    })
  })

  it('cancels title prompt dialog', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number, body?: string) => Error)(
        422, JSON.stringify({ detail: 'no_title' }),
      ),
    )
    const user = userEvent.setup()
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['no title'], 'notitle.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('Enter post title')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText('Enter post title')).not.toBeInTheDocument()
  })

  it('shows upload error message', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(new Error('Network'))
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['test'], 'test.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('Failed to upload post.')).toBeInTheDocument()
    })
  })

  it('shows 401 upload error', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      new (MockHTTPError as unknown as new (s: number) => Error)(401),
    )
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })

    const file = new File(['test'], 'test.md', { type: 'text/markdown' })
    await simulateFileUpload(file)

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  // === Filter URL sync ===

  it('passes filter params from URL to fetchPosts', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline('/?labels=swe,cs&author=Admin&from=2026-01-01&to=2026-02-01')

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledWith(
        expect.objectContaining({
          labels: 'swe,cs',
          author: 'Admin',
          from: '2026-01-01',
          to: '2026-02-01',
        }),
      )
    })
  })

  it('passes labelMode=and from URL', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline('/?labels=swe&labelMode=and')

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledWith(
        expect.objectContaining({
          labels: 'swe',
          labelMode: 'and',
        }),
      )
    })
  })
})
