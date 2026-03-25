import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { LabelResponse, PostListResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'

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
})
