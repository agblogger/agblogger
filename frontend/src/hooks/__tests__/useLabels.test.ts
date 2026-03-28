import { renderHook, waitFor, render, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import type { LabelResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { useAuthStore } from '@/stores/authStore'

const mockFetchLabels = vi.fn()
vi.mock('@/api/labels', () => ({
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
}))

import { useLabels } from '../useLabels'

const sampleLabels: LabelResponse[] = [
  {
    id: 'tech',
    names: ['Technology'],
    is_implicit: false,
    parents: [],
    children: ['web'],
    post_count: 5,
  },
  {
    id: 'web',
    names: ['Web Development'],
    is_implicit: false,
    parents: ['tech'],
    children: [],
    post_count: 3,
  },
]

describe('useLabels', () => {
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

  it('returns labels on success', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)

    const { result } = renderHook(() => useLabels(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(sampleLabels)
    })
    expect(result.current.error).toBeUndefined()
    expect(mockFetchLabels).toHaveBeenCalledOnce()
  })

  it('returns error when fetch fails', async () => {
    const fetchError = new Error('Network error')
    mockFetchLabels.mockRejectedValue(fetchError)

    const { result } = renderHook(() => useLabels(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.error).toBeDefined()
    })
    expect(result.current.data).toBeUndefined()
    expect(result.current.error).toBe(fetchError)
  })

  it('deduplicates requests when two consumers use the same key', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)

    function DualConsumer() {
      const r1 = useLabels()
      const r2 = useLabels()
      return createElement('div', {
        'data-r1': JSON.stringify(r1.data),
        'data-r2': JSON.stringify(r2.data),
      })
    }

    const { container } = render(
      createElement(SWRTestWrapper, null, createElement(DualConsumer, null)),
    )

    await waitFor(() => {
      const div = container.querySelector('div')
      expect(div?.getAttribute('data-r1')).not.toBeNull()
      const r1Data = JSON.parse(div?.getAttribute('data-r1') ?? 'null') as LabelResponse[] | null
      expect(r1Data).toEqual(sampleLabels)
    })

    const div = container.querySelector('div')
    const r1Data = JSON.parse(div?.getAttribute('data-r1') ?? 'null') as LabelResponse[] | null
    const r2Data = JSON.parse(div?.getAttribute('data-r2') ?? 'null') as LabelResponse[] | null
    expect(r1Data).toEqual(sampleLabels)
    expect(r2Data).toEqual(sampleLabels)
    expect(mockFetchLabels).toHaveBeenCalledOnce()
  })

  it('revalidates with a separate cache entry after logout', async () => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: 'admin',
        email: 'admin@example.com',
        display_name: 'Admin',
      },
    })
    mockFetchLabels
      .mockResolvedValueOnce([
        ...sampleLabels,
        {
          id: 'draft-only',
          names: ['Draft Only'],
          is_implicit: false,
          parents: [],
          children: [],
          post_count: 1,
        },
      ])
      .mockResolvedValueOnce(sampleLabels)

    const { result } = renderHook(() => useLabels(), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toHaveLength(3)
    })

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(sampleLabels)
    })

    expect(mockFetchLabels).toHaveBeenCalledTimes(2)
  })
})
