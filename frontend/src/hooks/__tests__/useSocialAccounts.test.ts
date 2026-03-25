import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { SocialAccount } from '@/api/crosspost'
import { SWRTestWrapper } from '@/test/swrWrapper'

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
  })

  it('returns social accounts on success', async () => {
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
})
