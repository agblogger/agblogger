import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { AssetListResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'

const mockAssets: AssetListResponse = {
  assets: [
    { name: 'image.png', size: 1024, is_image: true },
  ],
}

vi.mock('@/api/posts', () => ({
  fetchPostAssets: vi.fn(),
}))

import { fetchPostAssets } from '@/api/posts'
import { usePostAssets } from '../usePostAssets'

const mockFetchPostAssets = vi.mocked(fetchPostAssets)

function wrapper({ children }: { children: ReactNode }) {
  return createElement(SWRTestWrapper, null, children)
}

describe('usePostAssets', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns assets on success', async () => {
    mockFetchPostAssets.mockResolvedValueOnce(mockAssets)
    const { result } = renderHook(() => usePostAssets('posts/my-post'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockAssets)
    expect(result.current.error).toBeUndefined()
    expect(mockFetchPostAssets).toHaveBeenCalledWith('posts/my-post')
  })

  it('returns error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchPostAssets.mockRejectedValueOnce(err)
    const { result } = renderHook(() => usePostAssets('posts/my-post'), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
  })

  it('does not fetch when filePath is null', () => {
    const { result } = renderHook(() => usePostAssets(null), { wrapper })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetchPostAssets).not.toHaveBeenCalled()
  })

  it('refetches when refreshToken changes', async () => {
    mockFetchPostAssets.mockResolvedValue(mockAssets)
    const { result, rerender } = renderHook(
      ({ token }: { token: number }) => usePostAssets('posts/my-post', token),
      { wrapper, initialProps: { token: 0 } },
    )
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(mockFetchPostAssets).toHaveBeenCalledTimes(1)

    rerender({ token: 1 })
    await waitFor(() => expect(mockFetchPostAssets).toHaveBeenCalledTimes(2))
  })
})
