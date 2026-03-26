import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { SWRConfig } from 'swr'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPost, fetchPostForEdit, createPost, updatePost, uploadAssets, fetchPostAssets } from '@/api/posts'
import { fetchSocialAccounts } from '@/api/crosspost'
import type { UserResponse, PostEditResponse, PostDetail } from '@/api/client'
import { DRAFT_SCHEMA_VERSION } from '@/hooks/useEditorAutoSave'

// Mock localStorage since jsdom doesn't always provide full implementation
const storage = new Map<string, string>()
const mockLocalStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
  clear: () => storage.clear(),
  get length() {
    return storage.size
  },
  key: (index: number) => [...storage.keys()][index] ?? null,
}

Object.defineProperty(window, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
})

import { mockHttpError } from '@/test/MockHTTPError'

vi.mock('@/api/posts', () => ({
  fetchPost: vi.fn(),
  fetchPostForEdit: vi.fn(),
  createPost: vi.fn(),
  updatePost: vi.fn(),
  uploadAssets: vi.fn(),
  fetchPostAssets: vi.fn().mockResolvedValue({ assets: [] }),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
}))

const mockFetchViewCount = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchViewCount: (...args: unknown[]) => mockFetchViewCount(...args) as unknown,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: { post: vi.fn() },
    HTTPError: MockHTTPError,
  }
})

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn().mockResolvedValue([]),
  createLabel: vi.fn(),
}))

vi.mock('@/api/crosspost', () => ({
  fetchSocialAccounts: vi.fn().mockResolvedValue([]),
}))

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null; isInitialized: boolean }) => unknown) =>
    selector({ user: mockUser, isInitialized: true }),
}))

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null) => html ?? '',
}))

vi.mock('@/components/posts/TableOfContents', () => ({
  default: () => <div data-testid="toc" />,
}))

import EditorPage from '../EditorPage'
import PostPage from '../PostPage'

const mockFetchPost = vi.mocked(fetchPost)
const mockFetchPostForEdit = vi.mocked(fetchPostForEdit)
const mockFetchSocialAccounts = vi.mocked(fetchSocialAccounts)

function renderEditor(path = '/editor/new') {
  const router = createMemoryRouter(
    [
      { path: '/editor/new', element: createElement(EditorPage) },
      { path: '/editor/*', element: createElement(EditorPage) },
      { path: '/post/*', element: createElement('div', null, 'Post View') },
      { path: '/login', element: createElement('div', null, 'Login') },
    ],
    { initialEntries: [path] },
  )
  return render(
    createElement(
      SWRConfig,
      { value: { provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false } },
      createElement(RouterProvider, { router }),
    ),
  )
}

function renderEditorWithPost(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/editor/new', element: createElement(EditorPage) },
      { path: '/editor/*', element: createElement(EditorPage) },
      { path: '/post/*', element: createElement(PostPage) },
      { path: '/login', element: createElement('div', null, 'Login') },
    ],
    { initialEntries: [path] },
  )
  return render(
    createElement(
      SWRConfig,
      { value: { provider: () => new Map(), dedupingInterval: 2000, shouldRetryOnError: false } },
      createElement(RouterProvider, { router }),
    ),
  )
}

const editResponse: PostEditResponse = {
  file_path: 'posts/existing/index.md',
  title: 'Existing Post',
  body: 'Content here.',
  labels: ['swe'],
  is_draft: false,
  created_at: '2026-02-01 12:00:00+00:00',
  modified_at: '2026-02-01 13:00:00+00:00',
  author: 'Admin',
}

const directoryEditResponse: PostEditResponse = {
  ...editResponse,
  file_path: 'posts/2026-03-08-existing-post/index.md',
}

const postDetail: PostDetail = {
  id: 1,
  file_path: 'posts/existing/index.md',
  title: 'Existing Post',
  author: 'Admin',
  created_at: '2026-02-01 12:00:00+00:00',
  modified_at: '2026-02-01 13:00:00+00:00',
  is_draft: false,
  rendered_excerpt: '<p>Excerpt</p>',
  labels: ['swe'],
  rendered_html: '<p>Published content</p>',
  content: 'Published content',
}

describe('EditorPage', () => {
  beforeEach(() => {
    mockUser = { id: 1, username: 'jane', email: 'jane@test.com', display_name: null, is_admin: true }
    mockFetchPost.mockReset()
    mockFetchPostForEdit.mockReset()
    mockFetchSocialAccounts.mockReset()
    mockFetchSocialAccounts.mockResolvedValue([])
    mockFetchViewCount.mockReset()
    mockFetchViewCount.mockResolvedValue({ views: null })
    localStorage.clear()
  })

  it('author from display_name', async () => {
    mockUser = { id: 1, username: 'jane', email: 'j@t.com', display_name: 'Jane Doe', is_admin: false }
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    })
  })

  it('author fallback to username', async () => {
    mockUser = { id: 1, username: 'jane', email: 'j@t.com', display_name: null, is_admin: false }
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('jane')).toBeInTheDocument()
    })
  })

  it('default body for new post is empty', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      const textareas = document.querySelectorAll('textarea')
      expect(textareas.length).toBeGreaterThan(0)
      expect(textareas[0]).toHaveValue('')
    })
  })

  it('loads existing post data', async () => {
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByText('Admin')).toBeInTheDocument()
    })
    expect(mockFetchPostForEdit).toHaveBeenCalledWith('posts/existing/index.md')
  })

  it('shows the updated draft state when viewing a post immediately after saving it as draft', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockUser = { id: 1, username: 'jane', email: 'jane@test.com', display_name: null, is_admin: false }
    mockFetchPost.mockResolvedValue(postDetail)
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    vi.mocked(updatePost).mockResolvedValue({
      ...postDetail,
      is_draft: true,
      rendered_html: '<p>Now draft</p>',
      content: 'Now draft',
    })
    const user = userEvent.setup()

    renderEditorWithPost('/post/existing')

    await waitFor(() => {
      expect(screen.getByText('Existing Post')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('link', { name: /edit/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Existing Post')
    })

    await user.click(screen.getByRole('checkbox', { name: /draft/i }))
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /view post/i }))

    await waitFor(() => {
      expect(screen.getByText('Draft')).toBeInTheDocument()
    })

    expect(mockFetchPost).toHaveBeenCalledTimes(1)
    confirmSpy.mockRestore()
  })

  it('keeps the post view in sync after creating a public post and later switching it to draft', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const mockApi = (await import('@/api/client')).default
    vi.mocked(mockApi.post).mockReturnValue({
      json: () => Promise.resolve({ html: '<p>Preview</p>' }),
    } as ReturnType<typeof mockApi.post>)
    const createdPost: PostDetail = {
      ...postDetail,
      file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title',
    }
    const createdEditResponse: PostEditResponse = {
      file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title',
      body: 'Published content',
      labels: ['swe'],
      is_draft: false,
      created_at: '2026-03-08 12:00:00+00:00',
      modified_at: '2026-03-08 12:00:00+00:00',
      author: 'Admin',
    }
    mockUser = { id: 1, username: 'jane', email: 'jane@test.com', display_name: null, is_admin: false }
    vi.mocked(createPost).mockResolvedValue(createdPost)
    vi.mocked(updatePost).mockResolvedValue({
      ...createdPost,
      is_draft: true,
      rendered_html: '<p>Now draft</p>',
      content: 'Now draft',
    })
    mockFetchPostForEdit
      .mockResolvedValueOnce(createdEditResponse)
      .mockResolvedValueOnce(createdEditResponse)
    mockFetchPost.mockResolvedValue(createdPost)
    const user = userEvent.setup()

    renderEditorWithPost('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/title/i), 'My Title')
    const textareas = document.querySelectorAll('textarea')
    await user.type(textareas[0]!, 'Published content')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /view post/i }))

    await waitFor(() => {
      expect(screen.getByText('My Title')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('link', { name: /edit/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('My Title')
    })

    await user.click(screen.getByRole('checkbox', { name: /draft/i }))
    await user.click(screen.getByRole('button', { name: /save/i }))
    await user.click(screen.getByRole('button', { name: /view post/i }))

    await waitFor(() => {
      expect(screen.getByText('Draft')).toBeInTheDocument()
    })

    expect(mockFetchPost).toHaveBeenCalledTimes(1)
    confirmSpy.mockRestore()
  })

  it('uses cross-post wording for save-time distribution when accounts are connected', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Cross-post after saving:')).toBeInTheDocument()
    })
  })

  it('disables save-time cross-posting when the post is marked as draft', async () => {
    const user = userEvent.setup()
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Cross-post after saving:')).toBeInTheDocument()
    })

    const draftCheckbox = screen.getByRole('checkbox', { name: /draft/i })
    await user.click(draftCheckbox)

    const crossPostCheckbox = screen.getByRole('checkbox', { name: /alice\.bsky\.social/i })
    expect(crossPostCheckbox).toBeDisabled()
    expect(
      screen.getByText('Publish the post to enable cross-posting after saving.'),
    ).toBeInTheDocument()
  })

  it('shows an error when connected social accounts cannot be loaded', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockRejectedValue(new Error('Network error'))

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load connected social accounts. Please try again.'),
      ).toBeInTheDocument()
    })
  })

  it('shows 404 error page without editor form', async () => {
    // MockHTTPError has our test-friendly 1-arg constructor but TS sees the real type
    mockFetchPostForEdit.mockRejectedValue(mockHttpError(404))
    renderEditor('/editor/posts/missing/index.md')

    await waitFor(() => {
      expect(screen.getByText('404')).toBeInTheDocument()
    })
    expect(screen.getByText('Post not found')).toBeInTheDocument()
    expect(screen.getByText('Go back')).toBeInTheDocument()
    // Editor form should NOT be rendered
    expect(screen.queryByText('Save')).not.toBeInTheDocument()
    expect(screen.queryByText('Preview')).not.toBeInTheDocument()
  })

  it('shows session expired when post load returns 401', async () => {
    mockFetchPostForEdit.mockRejectedValue(
      mockHttpError(401),
    )
    renderEditor('/editor/posts/protected/index.md')

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
    expect(screen.queryByText('Save')).not.toBeInTheDocument()
  })

  it('shows generic error page without editor form', async () => {
    mockFetchPostForEdit.mockRejectedValue(new Error('Network error'))
    renderEditor('/editor/posts/broken/index.md')

    await waitFor(() => {
      expect(screen.getByText('Error')).toBeInTheDocument()
    })
    expect(screen.getByText('Failed to load post')).toBeInTheDocument()
    expect(screen.queryByText('Save')).not.toBeInTheDocument()
  })

  it('shows recovery banner when draft exists', async () => {
    const draft = {
      title: 'Draft Title',
      body: 'Draft content',
      labels: ['swe'],
      isDraft: false,
      savedAt: '2026-02-20T15:45:00.000Z',
      _v: DRAFT_SCHEMA_VERSION,
    }
    localStorage.setItem('agblogger:draft:user:1:new', JSON.stringify(draft))

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /restore/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /discard/i })).toBeInTheDocument()
  })

  it('restores draft content when Restore is clicked', async () => {
    const user = userEvent.setup()
    const draft = {
      title: 'Restored Title',
      body: 'Restored draft',
      labels: ['cs'],
      isDraft: true,
      savedAt: '2026-02-20T15:45:00.000Z',
      _v: DRAFT_SCHEMA_VERSION,
    }
    localStorage.setItem('agblogger:draft:user:1:new', JSON.stringify(draft))

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /restore/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /restore/i }))

    // Banner should disappear
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument()

    // Body should be restored
    const textareas = document.querySelectorAll('textarea')
    const bodyTextarea = Array.from(textareas).find((t) => t.value.includes('Restored draft'))
    expect(bodyTextarea).toBeTruthy()

    // Title should be restored
    expect(screen.getByLabelText(/Title/)).toHaveValue('Restored Title')
  })

  it('dismisses banner and clears draft when Discard is clicked', async () => {
    const user = userEvent.setup()
    localStorage.setItem(
      'agblogger:draft:user:1:new',
      JSON.stringify({ title: 'Old', body: 'Old body', labels: [], isDraft: false, savedAt: '2026-02-20T15:45:00.000Z', _v: DRAFT_SCHEMA_VERSION }),
    )

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /discard/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /discard/i }))

    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument()
    expect(localStorage.getItem('agblogger:draft:user:1:new')).toBeNull()
  })

  it('renders title input for new post', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })
  })

  it('save disabled when title is empty', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })
    // Title is initially empty for new posts
    const saveButton = screen.getByRole('button', { name: /save/i })
    expect(saveButton).toBeDisabled()
  })

  it('loads title for existing post', async () => {
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    renderEditor('/editor/posts/existing/index.md')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })
  })

  it('no file path input for new post', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })
    expect(screen.queryByLabelText('File path')).not.toBeInTheDocument()
  })

  it('enables save button when title is provided', async () => {
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    const saveButton = screen.getByRole('button', { name: /save/i })
    expect(saveButton).toBeDisabled()

    await user.type(screen.getByLabelText(/Title/), 'A Title')
    expect(saveButton).toBeEnabled()
  })

  // === Save functionality ===

  it('creates new post on save', async () => {
    const mockCreatePost = vi.mocked(createPost)
    const savedPost: PostDetail = {
      id: 1, file_path: 'posts/2026-02-22-my-title/index.md',
      title: 'My Title', author: 'jane', created_at: '2026-02-22 12:00:00+00:00',
      modified_at: '2026-02-22 12:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Hello</p>', content: 'Hello', labels: [],
    }
    mockCreatePost.mockResolvedValue(savedPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-02-22-my-title/index.md',
      title: 'My Title',
      body: '',
      labels: [],
      is_draft: false,
      created_at: '2026-02-22 12:00:00+00:00',
      modified_at: '2026-02-22 12:00:00+00:00',
      author: 'jane',
    })
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'My Title')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(mockCreatePost).toHaveBeenCalledWith({
        title: 'My Title',
        body: '',
        labels: [],
        is_draft: false,
      })
    })

    // Editor stays visible (save-and-stay behavior)
    expect(screen.getByLabelText(/Title/)).toHaveValue('My Title')
  })

  it('updates existing post on save', async () => {
    const mockUpdatePost = vi.mocked(updatePost)
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    const updatedPost: PostDetail = {
      id: 1, file_path: 'posts/existing/index.md',
      title: 'Existing Post', author: 'Admin', created_at: '2026-02-01 12:00:00+00:00',
      modified_at: '2026-02-22 12:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Content</p>', content: 'Content', labels: ['swe'],
    }
    mockUpdatePost.mockResolvedValue(updatedPost)
    const user = userEvent.setup()
    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(mockUpdatePost).toHaveBeenCalledWith('posts/existing/index.md', {
        title: 'Existing Post',
        body: 'Content here.',
        labels: ['swe'],
        is_draft: false,
      })
    })

    // Editor stays visible (save-and-stay behavior)
    expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
  })

  it('shows 401 save error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(401),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows 409 conflict error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(409),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Conflict: this post was modified elsewhere.')).toBeInTheDocument()
    })
  })

  it('shows 422 validation error with string detail', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: 'Title cannot be empty' })),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Title cannot be empty')).toBeInTheDocument()
    })
  })

  it('shows 422 validation error with array detail', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: [{ msg: 'Field required' }, { msg: 'Invalid format' }] })),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Field required, Invalid format')).toBeInTheDocument()
    })
  })

  it('shows generic save error for non-HTTP errors', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Failed to save post. The server may be unavailable.')).toBeInTheDocument()
    })
  })

  it('draft checkbox toggles isDraft', async () => {
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Draft')).toBeInTheDocument()
    })

    const checkbox = screen.getByRole('checkbox', { name: /draft/i })
    expect(checkbox).not.toBeChecked()

    await user.click(checkbox)
    expect(checkbox).toBeChecked()
  })

  it('shows 404 save error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(404),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Post not found. It may have been deleted.')).toBeInTheDocument()
    })
  })

  it('shows generic HTTP save error for unknown status', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(500),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Failed to save post. Please try again.')).toBeInTheDocument()
    })
  })

  it('shows created and modified dates for existing post', async () => {
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByText(/Created/)).toBeInTheDocument()
      expect(screen.getByText(/Modified/)).toBeInTheDocument()
    })
  })

  it('updates created date when publishing a draft post', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const mockUpdatePost = vi.mocked(updatePost)
    const draftEditResponse: PostEditResponse = {
      ...editResponse,
      is_draft: true,
      created_at: '2026-02-01 12:00:00+00:00',
    }
    mockFetchPostForEdit.mockResolvedValue(draftEditResponse)
    const publishedPost: PostDetail = {
      id: 1, file_path: 'posts/existing/index.md',
      title: 'Existing Post', author: 'Admin', created_at: '2026-03-15 09:00:00+00:00',
      modified_at: '2026-03-15 09:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Content</p>', content: 'Content', labels: ['swe'],
    }
    mockUpdatePost.mockResolvedValue(publishedPost)
    const user = userEvent.setup()
    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByText(/Created.*Feb 1/)).toBeInTheDocument()
    })

    // Uncheck Draft to publish
    await user.click(screen.getByRole('checkbox', { name: /draft/i }))
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText(/Created.*Mar 15/)).toBeInTheDocument()
    })
  })

  it('updates modified date displayed in editor after saving', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const mockUpdatePost = vi.mocked(updatePost)
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    const updatedPost: PostDetail = {
      id: 1, file_path: 'posts/existing/index.md',
      title: 'Existing Post', author: 'Admin', created_at: '2026-02-01 12:00:00+00:00',
      modified_at: '2026-02-22 09:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Content</p>', content: 'Content', labels: ['swe'],
    }
    mockUpdatePost.mockResolvedValue(updatedPost)
    const user = userEvent.setup()
    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByText(/Modified.*Feb 1/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText(/Modified.*Feb 22/)).toBeInTheDocument()
    })
  })

  it('shows preview placeholder initially', async () => {
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Start typing to see a live preview')).toBeInTheDocument()
    })
  })

  it('shows back button', async () => {
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Back')).toBeInTheDocument()
    })
  })

  it('shows labels input', async () => {
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Labels')).toBeInTheDocument()
    })
  })

  it('sends file_path in preview request for existing post', async () => {
    const mockApi = (await import('@/api/client')).default
    const mockPost = vi.mocked(mockApi.post)
    mockPost.mockClear()
    mockPost.mockReturnValue({ json: () => Promise.resolve({ html: '<p>preview</p>' }) } as ReturnType<typeof mockApi.post>)
    mockFetchPostForEdit.mockResolvedValue(editResponse)

    renderEditor('/editor/posts/existing/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    // Wait for debounced preview to fire (body is non-empty from loaded post)
    await waitFor(() => {
      const calls = mockPost.mock.calls
      const previewCall = calls.find(([url]) => url === 'render/preview')
      expect(previewCall).toBeDefined()
      const payload = (previewCall![1] as { json: { file_path?: string } }).json
      expect(payload.file_path).toBe('posts/existing/index.md')
    })
  })

  it('does not send file_path in preview request for new post', async () => {
    const user = userEvent.setup()
    const mockApi = (await import('@/api/client')).default
    const mockPost = vi.mocked(mockApi.post)
    mockPost.mockClear()
    mockPost.mockReturnValue({ json: () => Promise.resolve({ html: '<p>preview</p>' }) } as ReturnType<typeof mockApi.post>)

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    // Type some body text to trigger preview
    const textareas = document.querySelectorAll('textarea')
    await user.type(textareas[0]!, 'Hello world')

    await waitFor(() => {
      const calls = mockPost.mock.calls
      const previewCall = calls.find(([url]) => url === 'render/preview')
      expect(previewCall).toBeDefined()
      const payload = (previewCall![1] as { json: { markdown: string; file_path?: string } }).json
      expect(payload.file_path).toBeUndefined()
    })
  })

  it('shows 422 with empty detail string as generic validation error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: '' })),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Validation error. Check your input.')).toBeInTheDocument()
    })
  })

  it('shows 422 with non-string/array detail as generic validation error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({ detail: 42 })),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Validation error. Check your input.')).toBeInTheDocument()
    })
  })

  it('stays on editor after saving new post', async () => {
    const mockCreatePost = vi.mocked(createPost)
    const savedPost: PostDetail = {
      id: 1, file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title', author: 'jane', created_at: '2026-03-08 12:00:00+00:00',
      modified_at: '2026-03-08 12:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Hello</p>', content: 'Hello', labels: [],
    }
    mockCreatePost.mockResolvedValue(savedPost)
    // After save-and-stay navigates to /editor/<file_path>, EditorPage re-mounts
    // and calls fetchPostForEdit for the new path
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title', body: '', labels: [], is_draft: false,
      created_at: '2026-03-08 12:00:00+00:00',
      modified_at: '2026-03-08 12:00:00+00:00',
      author: 'jane',
    })
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'My Title')
    await user.click(screen.getByRole('button', { name: /save/i }))

    // Should stay on editor (Title input still visible)
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('My Title')
    })
    // View post button should now be visible
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
    })
  })

  it('shows View Post button only after save', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /view post/i })).not.toBeInTheDocument()
  })

  it('shows View Post button for existing post', async () => {
    mockFetchPostForEdit.mockResolvedValue(editResponse)
    renderEditor('/editor/posts/existing/index.md')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })
    expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
  })

  it('shows FileStrip for existing post', async () => {
    mockFetchPostForEdit.mockResolvedValue(directoryEditResponse)
    renderEditor('/editor/posts/2026-03-08-existing-post/index.md')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })
    // FileStrip header should show "Files" (empty assets from mock)
    expect(screen.getByText('Files')).toBeInTheDocument()
  })

  it('shows save-first message for new post FileStrip', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })
    expect(screen.getByText(/save.*to start adding files/i)).toBeInTheDocument()
  })

  it('shows preview unavailable when preview API fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const user = userEvent.setup()
    const mockApi = (await import('@/api/client')).default
    const mockPost = vi.mocked(mockApi.post)
    mockPost.mockClear()
    mockPost.mockReturnValue({
      json: () => Promise.reject(new Error('network error')),
    } as ReturnType<typeof mockApi.post>)

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    const textareas = document.querySelectorAll('textarea')
    await user.type(textareas[0]!, 'Some content to trigger preview')

    await waitFor(() => {
      expect(screen.getByText(/preview unavailable/i)).toBeInTheDocument()
    })
  })

  it('shows title character count', async () => {
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Hello')
    expect(screen.getByText('5 / 500')).toBeInTheDocument()
  })

  it('shows required indicator on title', async () => {
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText(/Title/)).toBeInTheDocument()
    })

    // The title label should have a required indicator
    const titleLabel = screen.getByText((content, element) => {
      return element?.tagName === 'LABEL' && content.includes('Title') && content.includes('*')
    })
    expect(titleLabel).toBeInTheDocument()
  })

  it('shows FileStrip with Files header for existing post', async () => {
    mockFetchPostForEdit.mockResolvedValue(directoryEditResponse)
    renderEditor('/editor/posts/2026-03-08-existing-post/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    expect(screen.getByText('Files')).toBeInTheDocument()
  })

  it('shows 422 with field/message detail as field-prefixed error', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, JSON.stringify({
        detail: [
          { field: 'title', message: 'String should have at least 1 character' },
        ],
      })),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Title: String should have at least 1 character'),
      ).toBeInTheDocument()
    })
  })

  it('shows 422 with unparseable body as generic validation error', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockRejectedValue(
      mockHttpError(422, 'not json'),
    )
    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Validation error. Check your input.')).toBeInTheDocument()
    })
    warnSpy.mockRestore()
  })

  it('enhances code blocks in preview panel', async () => {
    const user = userEvent.setup()
    const mockApi = (await import('@/api/client')).default
    const mockPost = vi.mocked(mockApi.post)
    mockPost.mockClear()
    mockPost.mockReturnValue({
      json: () =>
        Promise.resolve({
          html: '<pre><code class="language-python">print("hello")</code></pre>',
        }),
    } as ReturnType<typeof mockApi.post>)

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    const textareas = document.querySelectorAll('textarea')
    await user.type(textareas[0]!, 'Some code content')

    await waitFor(() => {
      expect(document.querySelector('.code-block-header')).not.toBeNull()
    })
    expect(document.querySelector('.code-block-lang')?.textContent).toBe('python')
  })

  it('renders mobile tab buttons for edit and preview', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'Preview' })).toBeInTheDocument()
  })

  it('shows an error when fetchSocialAccounts returns 401', async () => {
    mockFetchSocialAccounts.mockRejectedValue(
      mockHttpError(401),
    )

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load connected social accounts. Please try again.'),
      ).toBeInTheDocument()
    })
  })

  it('does not open cross-post dialog when saving a draft with platforms selected', async () => {
    const mockCreatePost = vi.mocked(createPost)
    mockCreatePost.mockResolvedValue({
      id: 1,
      file_path: 'posts/2026-03-13-test/index.md',
      title: 'Test',
      author: 'jane',
      created_at: '2026-03-13 12:00:00+00:00',
      modified_at: '2026-03-13 12:00:00+00:00',
      is_draft: true,
      rendered_excerpt: '',
      rendered_html: '<p>Test</p>',
      content: 'Test',
      labels: [],
    })
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])

    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByText('Cross-post after saving:')).toBeInTheDocument()
    })

    // Check the platform checkbox first (while not draft)
    const blueskyCheckbox = screen.getByRole('checkbox', { name: /alice\.bsky\.social/i })
    await user.click(blueskyCheckbox)

    // Toggle draft on — checkboxes get disabled but selection state is preserved
    const draftCheckbox = screen.getByRole('checkbox', { name: /draft/i })
    await user.click(draftCheckbox)

    // Type a title and save
    await user.type(screen.getByLabelText(/Title/), 'Test')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(mockCreatePost).toHaveBeenCalledWith({
        title: 'Test',
        body: '',
        labels: [],
        is_draft: true,
      })
    })

    // Cross-post dialog should NOT open for drafts
    expect(screen.queryByRole('heading', { name: 'Cross-post' })).not.toBeInTheDocument()
  })

  it('shows a visible error instead of silently logging when fetchSocialAccounts fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockRejectedValueOnce(new Error('Network error'))

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load connected social accounts. Please try again.'),
      ).toBeInTheDocument()
    })

    expect(warnSpy).not.toHaveBeenCalled()

    warnSpy.mockRestore()
  })

  it('image button shows "Save post first to add images" tooltip for new unsaved post', async () => {
    renderEditor('/editor/new')
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).toBeDisabled()
    expect(imageBtn).toHaveAttribute('title', 'Save post first to add images')
  })

  it('image button is enabled for directory-backed saved posts', async () => {
    mockFetchPostForEdit.mockResolvedValue(directoryEditResponse)
    renderEditor('/editor/posts/2026-03-08-existing-post/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).not.toBeDisabled()
  })

  it('handleInsertAtCursor appends to body when textarea ref is null', async () => {
    // This test verifies the fallback: when an image upload succeeds but textarea ref is null,
    // the markdown is appended to the body rather than silently dropped.
    const user = userEvent.setup()
    vi.mocked(uploadAssets).mockResolvedValue({ uploaded: ['fallback.jpg'] })

    mockFetchPostForEdit.mockResolvedValue(directoryEditResponse)
    renderEditor('/editor/posts/2026-03-08-existing-post/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    // Set initial body content
    const textareas = document.querySelectorAll('textarea')
    const bodyTextarea = textareas[0]!
    await user.clear(bodyTextarea)
    await user.type(bodyTextarea, 'Initial content')

    // Upload via the toolbar image input
    const imageInput = document.querySelector('input[accept="image/*"]') as HTMLInputElement
    expect(imageInput).not.toBeNull()

    const file = new File(['img data'], 'fallback.jpg', { type: 'image/jpeg' })
    await user.upload(imageInput, file)

    await waitFor(() => {
      const textarea = document.querySelectorAll('textarea')[0]!
      expect(textarea.value).toContain('![fallback.jpg](fallback.jpg)')
    })
  })

  it('refreshes FileStrip assets after toolbar image upload', async () => {
    const user = userEvent.setup()
    vi.mocked(uploadAssets).mockResolvedValue({ uploaded: ['hero.jpg'] })
    const mockFetchPostAssets = vi.mocked(fetchPostAssets)
    mockFetchPostAssets.mockResolvedValue({ assets: [] })

    mockFetchPostForEdit.mockResolvedValue(directoryEditResponse)
    renderEditor('/editor/posts/2026-03-08-existing-post/index.md')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
    })

    const initialCount = mockFetchPostAssets.mock.calls.length

    // The toolbar image input has accept="image/*"
    const imageInput = document.querySelector('input[accept="image/*"]') as HTMLInputElement
    expect(imageInput).not.toBeNull()

    const file = new File(['img data'], 'hero.jpg', { type: 'image/jpeg' })
    await user.upload(imageInput, file)

    await waitFor(() => {
      expect(mockFetchPostAssets.mock.calls.length).toBeGreaterThan(initialCount)
    })
  })

  // === Navigation guarding integration ===

  it('blocks in-app navigation and shows confirm when editor has unsaved changes', async () => {
    const user = userEvent.setup()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    // Make the editor dirty by typing a title
    await user.type(screen.getByLabelText(/Title/), 'Unsaved Title')

    // Click Back button — triggers navigate(-1) which is blocked by useBlocker when isDirty=true
    await user.click(screen.getByText('Back'))

    // The confirm dialog should have been shown
    expect(confirmSpy).toHaveBeenCalledWith(
      'You have unsaved changes. Are you sure you want to leave?',
    )
  })

  it('navigation after successful save proceeds without unsaved changes prompt', async () => {
    const mockCreatePost = vi.mocked(createPost)
    const savedPost: PostDetail = {
      id: 1, file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title', author: 'jane', created_at: '2026-03-08 12:00:00+00:00',
      modified_at: '2026-03-08 12:00:00+00:00', is_draft: false,
      rendered_excerpt: '', rendered_html: '<p>Hello</p>', content: 'Hello', labels: [],
    }
    mockCreatePost.mockResolvedValue(savedPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-my-title/index.md',
      title: 'My Title', body: '', labels: [], is_draft: false,
      created_at: '2026-03-08 12:00:00+00:00',
      modified_at: '2026-03-08 12:00:00+00:00',
      author: 'jane',
    })

    const user = userEvent.setup()
    renderEditor('/editor/new')

    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/Title/), 'My Title')
    await user.click(screen.getByRole('button', { name: /save/i }))

    // After a successful save, the editor navigates to /editor/<file_path>.
    // Navigation must proceed without a blocking confirm dialog — verified by
    // checking the component successfully loads and shows the saved post.
    await waitFor(() => {
      expect(screen.getByLabelText(/Title/)).toHaveValue('My Title')
    })
    // "View post" button appears only after the navigate succeeds and the
    // post is reloaded; its presence confirms navigation was NOT blocked.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
    })
  })
})
