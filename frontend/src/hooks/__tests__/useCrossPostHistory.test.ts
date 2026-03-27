import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { CrossPostHistory } from '@/api/crosspost'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { useAuthStore } from '@/stores/authStore'

const mockHistory: CrossPostHistory = {
  items: [
    {
      id: 1,
      post_path: 'posts/my-post',
      platform: 'bluesky',
      platform_id: 'abc123',
      status: 'posted',
      posted_at: '2024-01-01T00:00:00Z',
      error: null,
    },
  ],
}

vi.mock('@/api/crosspost', () => ({
  fetchCrossPostHistory: vi.fn(),
}))

import { fetchCrossPostHistory } from '@/api/crosspost'
import { useCrossPostHistory } from '../useCrossPostHistory'

const mockFetchCrossPostHistory = vi.mocked(fetchCrossPostHistory)

function wrapper({ children }: { children: ReactNode }) {
  return createElement(SWRTestWrapper, null, children)
}

describe('useCrossPostHistory', () => {
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

  it('returns history data on success', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'author',
        email: 'author@example.com',
        display_name: 'Author',
      },
    })
    mockFetchCrossPostHistory.mockResolvedValueOnce(mockHistory)
    const { result } = renderHook(() => useCrossPostHistory('posts/my-post'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockHistory)
    expect(result.current.error).toBeUndefined()
    expect(mockFetchCrossPostHistory).toHaveBeenCalledWith('posts/my-post')
  })

  it('returns error on failure', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'author',
        email: 'author@example.com',
        display_name: 'Author',
      },
    })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchCrossPostHistory.mockRejectedValueOnce(err)
    const { result } = renderHook(() => useCrossPostHistory('posts/my-post'), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
  })

  it('does not fetch when filePath is null', () => {
    const { result } = renderHook(() => useCrossPostHistory(null), { wrapper })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetchCrossPostHistory).not.toHaveBeenCalled()
  })

  it('does not fetch when logged out', () => {
    const { result } = renderHook(() => useCrossPostHistory('posts/my-post'), { wrapper })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetchCrossPostHistory).not.toHaveBeenCalled()
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
    mockFetchCrossPostHistory
      .mockResolvedValueOnce(mockHistory)
      .mockRejectedValueOnce(new Error('Unauthorized'))

    const { result } = renderHook(() => useCrossPostHistory('posts/my-post'), { wrapper })

    await waitFor(() => {
      expect(result.current.data).toEqual(mockHistory)
    })

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data).toBeUndefined()
    })

    expect(mockFetchCrossPostHistory).toHaveBeenCalledTimes(1)
  })
})
