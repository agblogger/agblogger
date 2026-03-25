import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { LabelGraphResponse } from '@/api/client'
import { SWRTestWrapper } from '@/test/swrWrapper'

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
})
