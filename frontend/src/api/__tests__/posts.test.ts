import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet, mockPost, mockPut, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
}))

import { createPost, deletePost, fetchPosts, searchPosts, updatePost } from '@/api/posts'

function mockJsonResponse(payload: unknown) {
  return { json: vi.fn().mockResolvedValue(payload) }
}

describe('fetchPosts', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockReturnValue(
      mockJsonResponse({ posts: [], total: 0, page: 1, per_page: 10, total_pages: 0 }),
    )
  })

  it('omits absent optional params from searchParams', async () => {
    await fetchPosts({ page: 1 })

    const [, options] = mockGet.mock.calls[0] as [string, { searchParams: URLSearchParams }]
    const params = options.searchParams
    expect(params.has('page')).toBe(true)
    expect(params.has('label')).toBe(false)
    expect(params.has('author')).toBe(false)
  })

  it('converts all param values to strings', async () => {
    await fetchPosts({ page: 2, per_page: 25 })

    const [, options] = mockGet.mock.calls[0] as [string, { searchParams: URLSearchParams }]
    const params = options.searchParams
    expect(params.get('page')).toBe('2')
    expect(params.get('per_page')).toBe('25')
  })

  it('passes string params unchanged', async () => {
    await fetchPosts({ label: 'swe', author: 'Admin', sort: 'created_at', order: 'desc' })

    const [, options] = mockGet.mock.calls[0] as [string, { searchParams: URLSearchParams }]
    const params = options.searchParams
    expect(params.get('label')).toBe('swe')
    expect(params.get('author')).toBe('Admin')
    expect(params.get('sort')).toBe('created_at')
    expect(params.get('order')).toBe('desc')
  })

  it('sends empty searchParams when no params given', async () => {
    await fetchPosts()

    const [url, options] = mockGet.mock.calls[0] as [string, { searchParams: URLSearchParams }]
    expect(url).toBe('posts')
    expect([...options.searchParams.entries()]).toHaveLength(0)
  })

  it('passes all filter params correctly', async () => {
    await fetchPosts({
      page: 1,
      per_page: 10,
      labels: 'swe,cs',
      labelMode: 'and',
      from: '2026-01-01',
      to: '2026-02-01',
    })

    const [, options] = mockGet.mock.calls[0] as [string, { searchParams: URLSearchParams }]
    const params = options.searchParams
    expect(params.get('labels')).toBe('swe,cs')
    expect(params.get('labelMode')).toBe('and')
    expect(params.get('from')).toBe('2026-01-01')
    expect(params.get('to')).toBe('2026-02-01')
  })
})

describe('searchPosts', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockReturnValue(mockJsonResponse([]))
  })

  it('passes query and default limit', async () => {
    await searchPosts('hello')

    const [url, options] = mockGet.mock.calls[0] as [
      string,
      { searchParams: { q: string; limit: string } },
    ]
    expect(url).toBe('posts/search')
    expect(options.searchParams.q).toBe('hello')
    expect(options.searchParams.limit).toBe('20')
  })

  it('passes custom limit as string', async () => {
    await searchPosts('test', 50)

    const [, options] = mockGet.mock.calls[0] as [
      string,
      { searchParams: { q: string; limit: string } },
    ]
    expect(options.searchParams.q).toBe('test')
    expect(options.searchParams.limit).toBe('50')
  })
})

describe('createPost', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('sends POST with correct JSON body', async () => {
    const newPost = { title: 'New Post', body: '# Hello', labels: ['swe'], is_draft: false }
    const responsePost = { file_path: 'new-post', ...newPost }
    mockPost.mockReturnValue(mockJsonResponse(responsePost))

    await createPost(newPost)

    const [url, options] = mockPost.mock.calls[0] as [string, { json: typeof newPost }]
    expect(url).toBe('posts')
    expect(options.json).toEqual(newPost)
  })
})

describe('updatePost', () => {
  beforeEach(() => {
    mockPut.mockReset()
  })

  it('sends PUT to correct path with JSON body', async () => {
    const params = { title: 'Updated', body: '# Updated', labels: ['cs'], is_draft: true }
    const responsePost = { file_path: 'my-post', ...params }
    mockPut.mockReturnValue(mockJsonResponse(responsePost))

    await updatePost('my-post', params)

    const [url, options] = mockPut.mock.calls[0] as [string, { json: typeof params }]
    expect(url).toBe('posts/my-post')
    expect(options.json).toEqual(params)
  })
})

describe('deletePost', () => {
  beforeEach(() => {
    mockDelete.mockReset()
  })

  it('sends DELETE to correct path', async () => {
    mockDelete.mockResolvedValue(undefined)

    await deletePost('my-post')

    const [url, options] = mockDelete.mock.calls[0] as [
      string,
      { searchParams: Record<string, string> | undefined },
    ]
    expect(url).toBe('posts/my-post')
    expect(options.searchParams).toBeUndefined()
  })

  it('sends delete_assets param when requested', async () => {
    mockDelete.mockResolvedValue(undefined)

    await deletePost('my-post', true)

    const [url, options] = mockDelete.mock.calls[0] as [
      string,
      { searchParams: { delete_assets: string } },
    ]
    expect(url).toBe('posts/my-post')
    expect(options.searchParams).toEqual({ delete_assets: 'true' })
  })
})
