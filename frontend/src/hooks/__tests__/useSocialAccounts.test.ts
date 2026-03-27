import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { SocialAccount } from '@/api/crosspost'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { useAuthStore } from '@/stores/authStore'

const mockFetchSocialAccounts = vi.fn()
vi.mock('@/api/crosspost', () => ({
  fetchSocialAccounts: (...args: unknown[]) => mockFetchSocialAccounts(...args) as unknown,
}))

import { useSocialAccounts } from '../useSocialAccounts'

const sampleAccounts: SocialAccount[] = [
  {
    id: 1,
    platform: 'bluesky',
    account_name: '@user.bsky.social',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    platform: 'mastodon',
    account_name: null,
    created_at: '2024-02-01T00:00:00Z',
  },
]

describe('useSocialAccounts', () => {
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

  it('returns social accounts on success', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'author',
        email: 'author@example.com',
        display_name: 'Author',
      },
    })
    mockFetchSocialAccounts.mockResolvedValue(sampleAccounts)

    const { result } = renderHook(() => useSocialAccounts(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(sampleAccounts)
    })
    expect(result.current.error).toBeUndefined()
    expect(mockFetchSocialAccounts).toHaveBeenCalledOnce()
  })

  it('returns error when fetch fails', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'author',
        email: 'author@example.com',
        display_name: 'Author',
      },
    })
    const fetchError = new Error('Unauthorized')
    mockFetchSocialAccounts.mockRejectedValue(fetchError)

    const { result } = renderHook(() => useSocialAccounts(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.error).toBeDefined()
    })
    expect(result.current.data).toBeUndefined()
    expect(result.current.error).toBe(fetchError)
  })

  it('does not fetch when logged out', () => {
    const { result } = renderHook(() => useSocialAccounts(), {
      wrapper: SWRTestWrapper,
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetchSocialAccounts).not.toHaveBeenCalled()
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
    mockFetchSocialAccounts
      .mockResolvedValueOnce(sampleAccounts)
      .mockResolvedValueOnce([])

    const { result } = renderHook(() => useSocialAccounts(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(sampleAccounts)
    })

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data).toBeUndefined()
    })

    expect(mockFetchSocialAccounts).toHaveBeenCalledTimes(1)
  })
})
