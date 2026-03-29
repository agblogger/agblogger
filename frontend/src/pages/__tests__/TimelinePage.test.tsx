import { createElement } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPosts, uploadPost } from '@/api/posts'
import type { PostListResponse, UserResponse } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'
import { localDateToUtcStart, localDateToUtcEnd } from '@/utils/date'

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

vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return {
    useAuthStore: create<{ user: UserResponse | null }>(() => ({ user: null })),
  }
})

const siteState = {
  config: {
    title: 'Blog',
    description: 'A blog',
    pages: [{ id: 'timeline', title: 'Posts', file: null }],
  },
}

vi.mock('@/stores/siteStore', () => ({
  useSiteStore: (selector: (s: typeof siteState) => unknown) => selector(siteState),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import { useAuthStore } from '@/stores/authStore'
import TimelinePage from '../TimelinePage'

function setMockUser(user: UserResponse | null) {
  useAuthStore.setState({ user })
}

const mockFetchPosts = vi.mocked(fetchPosts)
const mockUploadPost = vi.mocked(uploadPost)

const postsResponse: PostListResponse = {
  posts: [
    {
      id: 1,
      file_path: 'posts/hello/index.md',
      title: 'Hello World',
      subtitle: null,
      author: 'Admin',
      created_at: '2026-02-01 12:00:00+00:00',
      modified_at: '2026-02-01 12:00:00+00:00',
      is_draft: false,
      rendered_excerpt: '<p>First post</p>',
      labels: [],
    },
    {
      id: 2,
      file_path: 'posts/second/index.md',
      title: 'Second Post',
      subtitle: null,
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
  return {
    router,
    ...render(createElement(RouterProvider, { router })),
  }
}

describe('TimelinePage', () => {
  beforeEach(() => {
    mockFetchPosts.mockReset()
    mockUploadPost.mockReset()
    mockNavigate.mockReset()
    setMockUser(null)
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

  it('resets document.title to the site title on the timeline route', async () => {
    document.title = 'Hello World — Blog'
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(document.title).toBe('Blog')
    })
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue({ ...postsResponse, posts: [], total: 0 })
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('No posts yet')).toBeInTheDocument()
    })
    const cta = screen.getByRole('link', { name: 'Write your first post' })
    expect(cta).toBeInTheDocument()
    expect(cta).toHaveAttribute('href', '/editor/new')
  })

  it('re-fetches posts when user logs out', async () => {
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    const withDraft: PostListResponse = {
      posts: [
        {
          id: 1, file_path: 'posts/hello/index.md', title: 'Hello World', subtitle: null,
          author: 'Admin', created_at: '2026-02-01 12:00:00+00:00',
          modified_at: '2026-02-01 12:00:00+00:00', is_draft: false,
          rendered_excerpt: '<p>First post</p>', labels: [],
        },
        {
          id: 2, file_path: 'posts/my-draft/index.md', title: 'My Draft', subtitle: null,
          author: 'Admin', created_at: '2026-02-02 12:00:00+00:00',
          modified_at: '2026-02-02 12:00:00+00:00', is_draft: true,
          rendered_excerpt: '<p>Draft</p>', labels: [],
        },
      ],
      total: 2, page: 1, per_page: 10, total_pages: 1,
    }
    mockFetchPosts.mockResolvedValue(withDraft)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(mockFetchPosts).toHaveBeenCalledTimes(1)

    // Simulate logout: backend now returns only published posts
    const withoutDraft: PostListResponse = {
      posts: [withDraft.posts[0]!],
      total: 1, page: 1, per_page: 10, total_pages: 1,
    }
    mockFetchPosts.mockResolvedValue(withoutDraft)

    act(() => {
      setMockUser(null)
    })

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledTimes(2)
    })
    expect(screen.queryByText('My Draft')).not.toBeInTheDocument()
    expect(screen.getByText('Hello World')).toBeInTheDocument()
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline()

    await waitFor(() => {
      expect(screen.getByText('Upload file')).toBeInTheDocument()
    })
    expect(screen.getByText('Upload folder')).toBeInTheDocument()
  })

  it('hides upload buttons when not authenticated', async () => {
    setMockUser(null)
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockResolvedValue({
      id: 3, file_path: 'posts/uploaded/index.md', title: 'Uploaded', subtitle: null,
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
      expect(mockNavigate).toHaveBeenCalledWith('/post/uploaded')
    })
  })

  it('shows 413 error for large file upload', async () => {
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      mockHttpError(413),
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: 'no_title' })),
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost
      .mockRejectedValueOnce(
        mockHttpError(422, JSON.stringify({ detail: 'no_title' })),
      )
      .mockResolvedValueOnce({
        id: 3, file_path: 'posts/titled/index.md', title: 'My Title', subtitle: null,
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: 'no_title' })),
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
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
    setMockUser({ id: 1, username: 'admin', email: 'a@t.com', display_name: null })
    mockFetchPosts.mockResolvedValue(postsResponse)
    mockUploadPost.mockRejectedValue(
      mockHttpError(401),
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
    renderTimeline(
      `/?labels=swe,cs&author=Admin&from=${encodeURIComponent(localDateToUtcStart('2026-01-01'))}&to=${encodeURIComponent(localDateToUtcEnd('2026-02-01'))}`,
    )

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledWith(
        expect.objectContaining({
          labels: 'swe,cs',
          author: 'Admin',
          from: localDateToUtcStart('2026-01-01'),
          to: localDateToUtcEnd('2026-02-01'),
        }),
      )
    })
  })

  it('stores date filters in the URL as UTC ISO timestamps', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    const { router } = renderTimeline()

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledTimes(1)
    })

    const dateInputs = document.querySelectorAll('input[type="date"]')
    expect(dateInputs).toHaveLength(2)

    fireEvent.change(dateInputs[0] as HTMLInputElement, { target: { value: '2026-01-01' } })
    fireEvent.change(dateInputs[1] as HTMLInputElement, { target: { value: '2026-02-01' } })

    await waitFor(() => {
      expect(router.state.location.search).toContain(
        `from=${encodeURIComponent(localDateToUtcStart('2026-01-01'))}`,
      )
      expect(router.state.location.search).toContain(
        `to=${encodeURIComponent(localDateToUtcEnd('2026-02-01'))}`,
      )
    })

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenLastCalledWith(
        expect.objectContaining({
          from: localDateToUtcStart('2026-01-01'),
          to: localDateToUtcEnd('2026-02-01'),
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

  it('passes includeSublabels=true from URL to fetchPosts', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline('/?labels=swe&includeSublabels=true')

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalledWith(
        expect.objectContaining({
          includeSublabels: true,
        }),
      )
    })
  })

  it('does not pass includeSublabels when absent from URL', async () => {
    mockFetchPosts.mockResolvedValue(postsResponse)
    renderTimeline('/?labels=swe')

    await waitFor(() => {
      expect(mockFetchPosts).toHaveBeenCalled()
    })
    expect(mockFetchPosts).toHaveBeenCalledWith(
      expect.not.objectContaining({
        includeSublabels: expect.anything() as unknown,
      }),
    )
  })
})
