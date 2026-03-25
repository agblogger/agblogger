import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { SWRConfig } from 'swr'

import type { PageResponse } from '@/api/client'

const mockPage: PageResponse = {
  id: 'about',
  title: 'About',
  rendered_html: '<p>About us</p>',
}

const mockFetcher = vi.fn()

function wrapper({ children }: { children: ReactNode }) {
  return createElement(
    SWRConfig,
    { value: { fetcher: mockFetcher, provider: () => new Map(), dedupingInterval: 0 } },
    children,
  )
}

import { usePage } from '../usePage'

describe('usePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns page data on success', async () => {
    mockFetcher.mockResolvedValueOnce(mockPage)
    const { result } = renderHook(() => usePage('about'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockPage)
    expect(result.current.error).toBeUndefined()
    expect(mockFetcher).toHaveBeenCalledWith('pages/about')
  })

  it('returns error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetcher.mockRejectedValueOnce(err)
    const { result } = renderHook(() => usePage('about'), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
  })

  it('does not fetch when pageId is null', () => {
    const { result } = renderHook(() => usePage(null), { wrapper })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
    expect(mockFetcher).not.toHaveBeenCalled()
  })
})
