import type React from 'react'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPost, deletePost, updatePost, fetchPostForEdit } from '@/api/posts'
import type { UserResponse, PostDetail } from '@/api/client'
import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/posts', () => ({
  fetchPost: vi.fn(),
  deletePost: vi.fn(),
  updatePost: vi.fn(),
  fetchPostForEdit: vi.fn(),
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
  file_path: 'posts/hello.md',
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

function renderPostPage(path = '/post/posts/hello.md') {
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
    mockFetchPost.mockRejectedValue(new (MockHTTPError as unknown as new (s: number) => Error)(404))
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('404')).toBeInTheDocument()
    })
    expect(screen.getByText('Post not found')).toBeInTheDocument()
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
      expect(mockDeletePost).toHaveBeenCalledWith('posts/hello.md', false)
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
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
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
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

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
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

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
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockRejectedValue(new Error('Network error'))
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

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
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeDisabled()
    })
  })
})
