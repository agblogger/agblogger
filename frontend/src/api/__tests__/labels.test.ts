import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  default: { get: mockGet },
}))

import { fetchLabel, fetchLabelPosts } from '@/api/labels'

function mockJsonResponse(payload: unknown) {
  return { json: vi.fn().mockResolvedValue(payload) }
}

describe('fetchLabel', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('constructs URL with label ID', async () => {
    mockGet.mockReturnValue(mockJsonResponse({ id: 'swe', names: ['software engineering'] }))

    await fetchLabel('swe')

    expect(mockGet).toHaveBeenCalledWith('labels/swe')
  })

  it('handles label IDs with hyphens', async () => {
    mockGet.mockReturnValue(mockJsonResponse({ id: 'c-plus-plus', names: ['C++'] }))

    await fetchLabel('c-plus-plus')

    expect(mockGet).toHaveBeenCalledWith('labels/c-plus-plus')
  })
})

describe('fetchLabelPosts', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockReturnValue(
      mockJsonResponse({ posts: [], total: 0, page: 1, per_page: 20, total_pages: 0 }),
    )
  })

  it('converts page and perPage to strings', async () => {
    await fetchLabelPosts('swe', 2, 15)

    const [url, options] = mockGet.mock.calls[0] as [
      string,
      { searchParams: { page: string; per_page: string } },
    ]
    expect(url).toBe('labels/swe/posts')
    expect(options.searchParams.page).toBe('2')
    expect(options.searchParams.per_page).toBe('15')
  })

  it('uses default page=1 and perPage=20', async () => {
    await fetchLabelPosts('math')

    const [url, options] = mockGet.mock.calls[0] as [
      string,
      { searchParams: { page: string; per_page: string } },
    ]
    expect(url).toBe('labels/math/posts')
    expect(options.searchParams.page).toBe('1')
    expect(options.searchParams.per_page).toBe('20')
  })

  it('constructs URL with label ID', async () => {
    await fetchLabelPosts('cs', 3, 10)

    const [url] = mockGet.mock.calls[0] as [string]
    expect(url).toBe('labels/cs/posts')
  })
})
