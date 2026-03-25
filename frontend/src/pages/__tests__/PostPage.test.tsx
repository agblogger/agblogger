import type React from 'react'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPost, deletePost, updatePost, fetchPostForEdit } from '@/api/posts'
import type { UserResponse, PostDetail } from '@/api/client'
import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/posts', () => ({
  fetchPost: vi.fn(),
  deletePost: vi.fn(),
  updatePost: vi.fn(),
  fetchPostForEdit: vi.fn(),
}))

const mockFetchViewCount = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchViewCount: (...args: unknown[]) => mockFetchViewCount(...args) as unknown,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: {},
    HTTPError: MockHTTPError,
  }
})

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null | undefined) => html ?? '',
}))

vi.mock('@/components/labels/LabelChip', () => ({
  default: ({ labelId }: { labelId: string }) => <span data-testid="label">{labelId}</span>,
}))

vi.mock('@/api/crosspost', () => ({
  fetchCrossPostHistory: vi.fn().mockResolvedValue({ items: [] }),
  fetchSocialAccounts: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/components/posts/TableOfContents', () => ({
  default: ({ contentRef }: { contentRef: React.RefObject<HTMLElement | null> }) => (
    <div data-testid="toc" data-has-ref={!!contentRef.current} />
  ),
}))

import PostPage from '../PostPage'

const mockFetchPost = vi.mocked(fetchPost)
const mockDeletePost = vi.mocked(deletePost)
const mockUpdatePost = vi.mocked(updatePost)
const mockFetchPostForEdit = vi.mocked(fetchPostForEdit)

const postDetail: PostDetail = {
  id: 1,
  file_path: 'posts/hello/index.md',
  title: 'Hello World',
  author: 'Admin',
  created_at: '2026-02-01 12:00:00+00:00',
  modified_at: '2026-02-01 12:00:00+00:00',
  is_draft: false,
  rendered_excerpt: '<p>First post</p>',
  labels: [],
  rendered_html: '<p>Content here</p>',
  content: 'Content here',
}

const draftPost: PostDetail = {
  id: 2,
  file_path: 'posts/2026-03-08-draft/index.md',
  title: 'My Draft',
  author: 'Admin',
  created_at: '2026-03-08 10:00:00+00:00',
  modified_at: '2026-03-08 10:00:00+00:00',
  is_draft: true,
  rendered_excerpt: '<p>Draft excerpt</p>',
  labels: ['tech'],
  rendered_html: '<p>Draft content</p>',
  content: null,
}

let navigatedTo: string | number | null = null

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => (to: string | number, opts?: { replace?: boolean }) => {
      navigatedTo = to
      void opts
    },
  }
})

function renderPostPage(path = '/post/hello') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/post/*" element={<PostPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PostPage', () => {
  beforeEach(() => {
    mockUser = null
    navigatedTo = null
    mockFetchPost.mockReset()
    mockDeletePost.mockReset()
    mockUpdatePost.mockReset()
    mockFetchPostForEdit.mockReset()
    mockFetchViewCount.mockReset()
    mockFetchViewCount.mockResolvedValue({ views: null })
  })

  it('renders table of contents component', async () => {
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.getAllByTestId('toc').length).toBeGreaterThanOrEqual(1)
  })

  it('renders post content', async () => {
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.getByText('Content here')).toBeInTheDocument()
  })

  it('shows 404 for missing post', async () => {
    mockFetchPost.mockRejectedValue(mockHttpError(404))
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('404')).toBeInTheDocument()
    })
    expect(screen.getByText('Post not found')).toBeInTheDocument()
  })

  it('shows session expired error when loading post returns 401', async () => {
    mockFetchPost.mockRejectedValue(
      mockHttpError(401),
    )
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('hides delete button when not authenticated', async () => {
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.queryByText('Delete')).not.toBeInTheDocument()
  })

  it('shows delete button when authenticated', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
  })

  it('shows confirmation dialog on delete click', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))

    expect(screen.getByText('Delete post?')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
    expect(screen.getByText(/This will permanently delete/)).toBeInTheDocument()
  })

  it('cancel closes confirmation dialog', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    expect(screen.getByText('Delete post?')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Delete post?')).not.toBeInTheDocument()
  })

  it('shows unified single-button confirmation dialog for directory-backed post', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))

    expect(screen.getByText('Delete post?')).toBeInTheDocument()
    // Unified warning message (same for all post types)
    expect(screen.getByText(/This will permanently delete/)).toBeInTheDocument()
    // Single confirm button — not the two-option UI
    expect(screen.getByTestId('confirm-delete')).toBeInTheDocument()
    expect(screen.queryByText('Delete post only')).not.toBeInTheDocument()
    expect(screen.queryByText('Delete with all files')).not.toBeInTheDocument()
  })

  it('confirming delete navigates to home', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    mockDeletePost.mockResolvedValue(undefined)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))

    await userEvent.click(screen.getByTestId('confirm-delete'))

    await waitFor(() => {
      expect(mockDeletePost).toHaveBeenCalledWith('posts/hello/index.md', true)
    })
    expect(navigatedTo).toBe('/')
  })

  it('renders title from metadata not from rendered HTML', async () => {
    const postWithNoH1 = {
      ...postDetail,
      rendered_html: '<p>Just body content</p>',
    }
    mockFetchPost.mockResolvedValue(postWithNoH1)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Hello World')
    })
    expect(screen.getByText('Just body content')).toBeInTheDocument()
  })

  it('shows error on delete failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    mockDeletePost.mockRejectedValue(new Error('Network error'))
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))

    await userEvent.click(screen.getByTestId('confirm-delete'))

    await waitFor(() => {
      expect(screen.getByText('Failed to delete post. Please try again.')).toBeInTheDocument()
    })
    // Dialog should be closed after error
    expect(screen.queryByText('Delete post?')).not.toBeInTheDocument()
  })

  it('shows session expired error on 401 delete failure', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    mockDeletePost.mockRejectedValue(
      mockHttpError(401),
    )
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByTestId('confirm-delete'))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
    expect(screen.queryByText('Delete post?')).not.toBeInTheDocument()
  })

  it('renders share button for unauthenticated users', async () => {
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    // Header ShareButton + bottom ShareBar both have "Share this post" buttons
    const shareButtons = screen.getAllByRole('button', { name: 'Share this post' })
    expect(shareButtons.length).toBeGreaterThanOrEqual(2)
  })

  it('renders share bar for unauthenticated users', async () => {
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    // Bottom share bar shows Share, Email, and Copy Link directly (platforms are in dropdown)
    const shareButtons = screen.getAllByRole('button', { name: 'Share this post' })
    expect(shareButtons.length).toBeGreaterThanOrEqual(2) // header + bar
    expect(screen.getByRole('button', { name: 'Share via email' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
  })

  it('renders definition list elements in prose content', async () => {
    const postWithDl = {
      ...postDetail,
      rendered_html: '<dl><dt>Term</dt><dd>Definition text</dd></dl>',
    }
    mockFetchPost.mockResolvedValue(postWithDl)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    const dl = document.querySelector('.prose dl')
    expect(dl).toBeInTheDocument()
    expect(document.querySelector('.prose dt')).toHaveTextContent('Term')
    expect(document.querySelector('.prose dd')).toHaveTextContent('Definition text')
  })

  it('renders task list checkbox items in prose content', async () => {
    const postWithTaskList = {
      ...postDetail,
      rendered_html:
        '<ul><li><input type="checkbox" disabled>Unchecked</li>' +
        '<li><input type="checkbox" checked disabled>Checked</li></ul>',
    }
    mockFetchPost.mockResolvedValue(postWithTaskList)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    const checkboxes = document.querySelectorAll('.prose input[type="checkbox"]')
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes[0]).not.toBeChecked()
    expect(checkboxes[1]).toBeChecked()
  })

  it('renders share UI and cross-posting section for admin users', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    // Both header ShareButton and bottom ShareBar render Share buttons
    const shareButtons = screen.getAllByRole('button', { name: 'Share this post' })
    expect(shareButtons.length).toBeGreaterThanOrEqual(2)
  })

  it('shows draft badge and publish button for draft post when authenticated', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    const shareButtons = screen.getAllByRole('button', { name: 'Share this post' })
    expect(shareButtons.length).toBeGreaterThanOrEqual(2)
    for (const button of shareButtons) {
      expect(button).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: 'Share via email' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeDisabled()
    expect(screen.getByText('Publish this draft to enable cross-posting.')).toBeInTheDocument()
  })

  it('does not show draft badge or publish button for published post', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()
  })

  it('does not show draft badge or publish button for unauthenticated user', async () => {
    mockFetchPost.mockResolvedValue(draftPost)
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()
  })

  it('publish button calls update API with is_draft false', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-draft/index.md',
      title: 'My Draft',
      body: 'Draft content.\n',
      labels: ['tech'],
      is_draft: true,
      created_at: '2026-03-08 10:00:00+00:00',
      modified_at: '2026-03-08 10:00:00+00:00',
      author: 'Admin',
    })
    const publishedPost = { ...draftPost, is_draft: false }
    mockUpdatePost.mockResolvedValue(publishedPost)
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(mockUpdatePost).toHaveBeenCalledWith(
        'posts/2026-03-08-draft/index.md',
        expect.objectContaining({ is_draft: false }),
      )
    })
  })

  it('shows error message on publish failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockRejectedValue(new Error('Network error'))
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(screen.getByText('Failed to publish post. Please try again.')).toBeInTheDocument()
    })
    // Button should be re-enabled after failure
    expect(screen.getByRole('button', { name: /publish/i })).toBeEnabled()
  })

  it('publish button is disabled during API call', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockImplementation(
      () => new Promise(() => {}),
    )
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeDisabled()
    })
  })
  it('shows server detail on 409 publish failure', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-draft/index.md',
      title: 'My Draft',
      body: 'Draft content.\n',
      labels: ['tech'],
      is_draft: true,
      created_at: '2026-03-08 10:00:00+00:00',
      modified_at: '2026-03-08 10:00:00+00:00',
      author: 'Admin',
    })
    mockUpdatePost.mockRejectedValue(
      mockHttpError(409, JSON.stringify({ detail: 'Post was modified by another user' })),
    )
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Post was modified by another user'),
      ).toBeInTheDocument()
    })
  })

  it('shows generic error on 500 publish failure', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-draft/index.md',
      title: 'My Draft',
      body: 'Draft content.\n',
      labels: ['tech'],
      is_draft: true,
      created_at: '2026-03-08 10:00:00+00:00',
      modified_at: '2026-03-08 10:00:00+00:00',
      author: 'Admin',
    })
    mockUpdatePost.mockRejectedValue(
      mockHttpError(500, JSON.stringify({ detail: 'Internal server error' })),
    )
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to publish post. Please try again.'),
      ).toBeInTheDocument()
    })
  })

  it('publish error is rendered via AlertBanner with mt-3 spacing class', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockRejectedValue(new Error('Network error'))
    renderPostPage('/post/2026-03-08-draft')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      const errorEl = screen.getByText('Failed to publish post. Please try again.')
      // AlertBanner with className="mt-3" should add mt-3 to the wrapper div
      expect(errorEl.closest('div')).toHaveClass('mt-3')
    })
  })

  it('displays view count when analytics returns a count', async () => {
    mockFetchViewCount.mockResolvedValue({ views: 1234 })
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('1,234 views')).toBeInTheDocument()
    })
  })

  it('does not display view count when analytics returns null', async () => {
    mockFetchViewCount.mockResolvedValue({ views: null })
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    // Wait a tick for the view count fetch to resolve
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(screen.queryByText(/views$/)).not.toBeInTheDocument()
  })

  it('does not display view count when analytics fetch fails', async () => {
    mockFetchViewCount.mockRejectedValue(new Error('unavailable'))
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(screen.queryByText(/views$/)).not.toBeInTheDocument()
  })

  it('delete error is rendered via AlertBanner with mb-6 spacing class', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    mockDeletePost.mockRejectedValue(new Error('Network error'))
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByTestId('confirm-delete'))

    await waitFor(() => {
      const errorEl = screen.getByText('Failed to delete post. Please try again.')
      // AlertBanner with className="mb-6" should add mb-6 to the wrapper div
      expect(errorEl.closest('div')).toHaveClass('mb-6')
    })
  })
})
