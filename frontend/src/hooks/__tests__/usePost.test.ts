import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

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

describe('usePost', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
