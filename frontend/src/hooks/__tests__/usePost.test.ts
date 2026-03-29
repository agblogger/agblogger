import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { MockHTTPError } from '@/test/MockHTTPError'
import { useAuthStore } from '@/stores/authStore'

const mockFetchPost = vi.fn()
vi.mock('@/api/posts', () => ({
  fetchPost: (...args: unknown[]) => mockFetchPost(...args) as unknown,
}))

const mockFetchViewCount = vi.fn()
vi.mock('@/api/analytics', () => ({
  fetchViewCount: (...args: unknown[]) => mockFetchViewCount(...args) as unknown,
}))

import { usePost, useViewCount } from '../usePost'
import type { PostDetail, ViewCountResponse } from '@/api/client'

const postDetail: PostDetail = {
  id: 1,
  title: 'My Post',
  subtitle: null,
  file_path: 'my-post/index.md',
  author: 'admin',
  created_at: '2026-01-01T00:00:00Z',
  modified_at: '2026-01-01T00:00:00Z',
  is_draft: false,
  rendered_excerpt: null,
  labels: [],
  rendered_html: '<p>Hello</p>',
  content: '# Hello',
}

const viewCountResponse: ViewCountResponse = { views: 42 }

function injectPostPreload(post: PostDetail) {
  document.body.innerHTML = `
    <div id="root"><div data-content>${post.rendered_html}</div></div>
    <script id="__initial_data__" type="application/json">${JSON.stringify({
      ...post,
      rendered_html: undefined,
    })}</script>
  `
}

describe('usePost', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    useAuthStore.setState({
      user: null,
      isLoading: false,
      isLoggingOut: false,
      isInitialized: false,
      error: null,
    })
  })

  it('fetches post by slug', async () => {
    mockFetchPost.mockResolvedValue(postDetail)

    const { result } = renderHook(() => usePost('my-post/index.md'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(postDetail)
    })

    expect(mockFetchPost).toHaveBeenCalledWith('my-post/index.md')
  })

  it('does not fetch when slug is null', async () => {
    const { result } = renderHook(() => usePost(null), {
      wrapper: SWRTestWrapper,
    })

    // Allow microtasks to settle
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchPost).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })

  it('revalidates with a separate cache entry after logout', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'author',
        email: 'author@example.com',
        display_name: 'Author',
      },
    })
    mockFetchPost.mockResolvedValueOnce({
      ...postDetail,
      is_draft: true,
      author: 'author',
    })

    const { result } = renderHook(() => usePost('draft-post/index.md'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data?.is_draft).toBe(true)
    })

    mockFetchPost.mockRejectedValueOnce(new MockHTTPError(404))

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data).toBeUndefined()
      expect(result.current.error).toBeInstanceOf(MockHTTPError)
    })

    expect(mockFetchPost).toHaveBeenNthCalledWith(1, 'draft-post/index.md')
    expect(mockFetchPost).toHaveBeenNthCalledWith(2, 'draft-post/index.md')
  })

  it('does not reuse preloaded fallback after the slug changes', async () => {
    injectPostPreload(postDetail)
    mockFetchPost.mockImplementation(() => new Promise(() => {}))

    const { result, rerender } = renderHook(
      ({ slug }: { slug: string | null }) => usePost(slug),
      {
        initialProps: { slug: 'my-post/index.md' },
        wrapper: SWRTestWrapper,
      },
    )

    expect(result.current.data?.title).toBe('My Post')

    rerender({ slug: 'other-post/index.md' })

    await waitFor(() => {
      expect(result.current.data).toBeUndefined()
    })
  })
})

describe('useViewCount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches view count by slug', async () => {
    mockFetchViewCount.mockResolvedValue(viewCountResponse)

    const { result } = renderHook(() => useViewCount('my-post/index.md'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(viewCountResponse)
    })

    expect(mockFetchViewCount).toHaveBeenCalledWith('my-post/index.md')
  })

  it('does not fetch when slug is null', async () => {
    const { result } = renderHook(() => useViewCount(null), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchViewCount).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })
})
