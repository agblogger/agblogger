import { renderHook, waitFor, act } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { LabelGraphResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { useAuthStore } from '@/stores/authStore'

const mockGraph: LabelGraphResponse = {
  nodes: [{ id: 'tech', names: ['Technology'], post_count: 5 }],
  edges: [{ source: 'tech', target: 'programming' }],
}

vi.mock('@/api/labels', () => ({
  fetchLabelGraph: vi.fn(),
  fetchLabel: vi.fn(),
  fetchLabelPosts: vi.fn(),
}))

import { fetchLabelGraph } from '@/api/labels'
import { useLabelGraph } from '../useLabelGraph'

const mockFetchLabelGraph = vi.mocked(fetchLabelGraph)

function wrapper({ children }: { children: ReactNode }) {
  return createElement(SWRTestWrapper, null, children)
}

describe('useLabelGraph', () => {
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

  it('returns data on success', async () => {
    mockFetchLabelGraph.mockResolvedValueOnce(mockGraph)
    const { result } = renderHook(() => useLabelGraph(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(mockGraph)
    expect(result.current.error).toBeUndefined()
  })

  it('returns error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('fetch failed')
    mockFetchLabelGraph.mockRejectedValueOnce(err)
    const { result } = renderHook(() => useLabelGraph(), { wrapper })
    await waitFor(() => expect(result.current.error).toBeDefined())
    expect(result.current.error).toBe(err)
    expect(result.current.data).toBeUndefined()
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
    mockFetchLabelGraph
      .mockResolvedValueOnce({
        nodes: [
          ...mockGraph.nodes,
          { id: 'draft-only', names: ['Draft Only'], post_count: 1 },
        ],
        edges: mockGraph.edges,
      })
      .mockResolvedValueOnce(mockGraph)

    const { result } = renderHook(() => useLabelGraph(), { wrapper })

    await waitFor(() => {
      expect(result.current.data?.nodes).toHaveLength(2)
    })

    act(() => {
      useAuthStore.setState({ user: null })
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(mockGraph)
    })

    expect(mockFetchLabelGraph).toHaveBeenCalledTimes(2)
  })
})
