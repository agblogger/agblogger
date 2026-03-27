import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { LabelResponse, PostListResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { useAuthStore } from '@/stores/authStore'

const mockLabel: LabelResponse = {
  id: 'tech',
  names: ['Technology'],
  is_implicit: false,
  parents: [],
  children: [],
  post_count: 3,
}

const mockPosts: PostListResponse = {
  posts: [],
  total: 0,
  page: 1,
  per_page: 20,
  total_pages: 0,
}

vi.mock('@/api/labels', () => ({
  fetchLabelGraph: vi.fn(),
  fetchLabel: vi.fn(),
  fetchLabelPosts: vi.fn(),
}))

import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import { useLabelPosts } from '../useLabelPosts'

const mockFetchLabel = vi.mocked(fetchLabel)
const mockFetchLabelPosts = vi.mocked(fetchLabelPosts)

function wrapper({ children }: { children: ReactNode }) {
  return createElement(SWRTestWrapper, null, children)
}

describe('useLabelPosts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      user: null,
      isLoading: false,
      isLoggingOut: false,
      isInitialized: false,
      error: null,
    })
  })

  it('returns combined label and posts data on success', async () => {
    mockFetchLabel.mockResolvedValueOnce(mockLabel)
    mockFetchLabelPosts.mockResolvedValueOnce(mockPosts)
    const { result } = renderHook(() => useLabelPosts('tech'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual({ label: mockLabel, posts: mockPosts })
    expect(result.current.error).toBeUndefined()
  })

  it('returns error when fetch fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchLabel.mockRejectedValueOnce(err)
    mockFetchLabelPosts.mockResolvedValueOnce(mockPosts)
    const { result } = renderHook(() => useLabelPosts('tech'), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBeDefined()
    expect(result.current.data).toBeUndefined()
  })

  it('does not fetch when labelId is null', () => {
    const { result } = renderHook(() => useLabelPosts(null), { wrapper })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetchLabel).not.toHaveBeenCalled()
    expect(mockFetchLabelPosts).not.toHaveBeenCalled()
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
    mockFetchLabel.mockResolvedValue(mockLabel)
    mockFetchLabelPosts
      .mockResolvedValueOnce({
        ...mockPosts,
        posts: [
          {
            id: 1,
            file_path: 'posts/draft-post/index.md',
            title: 'Draft Post',
            subtitle: null,
            author: 'author',
            created_at: '2026-01-01T00:00:00Z',
            modified_at: '2026-01-01T00:00:00Z',
            is_draft: true,
            rendered_excerpt: '<p>Draft</p>',
            labels: ['tech'],
          },
        ],
        total: 1,
        total_pages: 1,
      })
      .mockResolvedValueOnce(mockPosts)

    const { result } = renderHook(() => useLabelPosts('tech'), { wrapper })

    await waitFor(() => {
      expect(result.current.data?.posts.posts).toHaveLength(1)
    })

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data?.posts.posts).toHaveLength(0)
    })

    expect(mockFetchLabelPosts).toHaveBeenCalledTimes(2)
  })
})
