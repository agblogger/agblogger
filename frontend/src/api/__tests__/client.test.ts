import { beforeEach, describe, expect, it, vi } from 'vitest'

interface JsonResponse<T> {
  json: () => Promise<T>
}

interface MockKyHooks {
  beforeRequest: [(request: Request) => Promise<void>]
  afterResponse: [(request: Request, options: unknown, response: Response) => Promise<Response>]
}

let capturedHooks: MockKyHooks | null = null
const mockKyPost = vi.fn()
const mockKyGet = vi.fn()
const mockKyRequest = vi.fn()

vi.mock('ky', () => {
  class HTTPError extends Error {
    response: { status: number }

    constructor(message: string, options?: { response?: { status: number } }) {
      super(message)
      this.response = options?.response ?? { status: 500 }
    }
  }

  const kyFn = Object.assign(mockKyRequest, {
    create: (config: { hooks?: MockKyHooks }) => {
      capturedHooks = config.hooks ?? null
      return { get: vi.fn(), post: mockKyPost, put: vi.fn(), delete: vi.fn() }
    },
    get: mockKyGet,
    post: mockKyPost,
    HTTPError,
  })

  return { default: kyFn, HTTPError }
})

const { clearCsrfToken } = await import('@/api/client')

function mockJsonResponse<T>(payload: T): JsonResponse<T> {
  return { json: vi.fn().mockResolvedValue(payload) }
}

describe('client CSRF hooks', () => {
  beforeEach(() => {
    clearCsrfToken()
    mockKyGet.mockReset()
    mockKyPost.mockReset()
    mockKyRequest.mockReset()
  })

  it('captures hooks from ky.create', () => {
    expect(capturedHooks).not.toBeNull()
    expect(capturedHooks!.beforeRequest).toHaveLength(1)
    expect(capturedHooks!.afterResponse).toHaveLength(1)
  })

  describe('beforeRequest hook', () => {
    it('fetches a CSRF token for unsafe requests', async () => {
      mockKyGet.mockReturnValue(mockJsonResponse({ csrf_token: 'server-csrf-token' }))
      const request = new Request('https://example.com/api/posts', { method: 'POST' })

      await capturedHooks!.beforeRequest[0](request)

      expect(request.headers.get('X-CSRF-Token')).toBe('server-csrf-token')
      expect(mockKyGet).toHaveBeenCalledWith(
        'auth/csrf',
        expect.objectContaining({
          prefixUrl: '/api',
          credentials: 'include',
        }),
      )
    })

    it('reuses the cached CSRF token across unsafe requests', async () => {
      mockKyGet.mockReturnValue(mockJsonResponse({ csrf_token: 'cached-csrf-token' }))
      const firstRequest = new Request('https://example.com/api/posts', { method: 'POST' })
      const secondRequest = new Request('https://example.com/api/posts/1', { method: 'DELETE' })

      await capturedHooks!.beforeRequest[0](firstRequest)
      await capturedHooks!.beforeRequest[0](secondRequest)

      expect(firstRequest.headers.get('X-CSRF-Token')).toBe('cached-csrf-token')
      expect(secondRequest.headers.get('X-CSRF-Token')).toBe('cached-csrf-token')
      expect(mockKyGet).toHaveBeenCalledTimes(1)
    })

    it('does not fetch a CSRF token for safe requests', async () => {
      const request = new Request('https://example.com/api/posts', { method: 'GET' })

      await capturedHooks!.beforeRequest[0](request)

      expect(request.headers.get('X-CSRF-Token')).toBeNull()
      expect(mockKyGet).not.toHaveBeenCalled()
    })
  })

  describe('afterResponse hook', () => {
    it('refreshes on 401 and retries unsafe requests with the new CSRF token', async () => {
      mockKyGet.mockReturnValue(mockJsonResponse({ csrf_token: 'old-csrf-token' }))
      mockKyPost.mockReturnValue(
        mockJsonResponse({
          csrf_token: 'new-csrf-token',
        }),
      )
      mockKyRequest.mockResolvedValue(new Response('ok', { status: 200 }))

      const request = new Request('https://example.com/api/posts', { method: 'POST' })
      await capturedHooks!.beforeRequest[0](request)
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(200)
      expect(mockKyPost).toHaveBeenCalledWith(
        'auth/refresh',
        expect.objectContaining({
          prefixUrl: '/api',
          credentials: 'include',
        }),
      )
      expect(mockKyRequest).toHaveBeenCalledTimes(1)
      const retryRequest: unknown = mockKyRequest.mock.calls[0]?.[0]
      expect(retryRequest).toBeInstanceOf(Request)
      expect((retryRequest as Request).headers.get('X-CSRF-Token')).toBe('new-csrf-token')
    })

    it('does not retry already retried requests', async () => {
      const headers = new Headers({ 'X-Auth-Retry': '1' })
      const request = new Request('https://example.com/api/posts', { method: 'GET', headers })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('does not retry the auth refresh endpoint', async () => {
      const request = new Request('https://example.com/api/auth/refresh', { method: 'POST' })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('does not retry GET auth/me (auth check)', async () => {
      const request = new Request('https://example.com/api/auth/me', { method: 'GET' })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('does not retry POST auth/login (invalid credentials)', async () => {
      const request = new Request('https://example.com/api/auth/login', { method: 'POST' })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('still retries PATCH auth/me (profile update with expired token)', async () => {
      mockKyGet.mockReturnValue(mockJsonResponse({ csrf_token: 'old-csrf-token' }))
      mockKyPost.mockReturnValue(mockJsonResponse({ csrf_token: 'new-csrf-token' }))
      mockKyRequest.mockResolvedValue(new Response('ok', { status: 200 }))

      const request = new Request('https://example.com/api/auth/me', { method: 'PATCH' })
      await capturedHooks!.beforeRequest[0](request)
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(200)
      expect(mockKyPost).toHaveBeenCalledWith(
        'auth/refresh',
        expect.objectContaining({ prefixUrl: '/api' }),
      )
    })

    it('returns non-401 responses unchanged', async () => {
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('ok', { status: 200 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(200)
      expect(mockKyPost).not.toHaveBeenCalled()
      expect(mockKyRequest).not.toHaveBeenCalled()
    })
  })
})
