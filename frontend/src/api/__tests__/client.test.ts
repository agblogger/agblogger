import { describe, it, expect, vi, beforeEach } from 'vitest'

// We test the CSRF token and retry logic by examining the ky configuration.
// Since the module under test creates a ky instance, we mock ky to capture hooks.

interface MockKyHooks {
  beforeRequest: [(request: Request) => void]
  afterResponse: [(request: Request, options: unknown, response: Response) => Promise<Response>]
}

let capturedHooks: MockKyHooks | null = null
const mockKyPost = vi.fn()

vi.mock('ky', () => {
  class HTTPError extends Error {
    response: { status: number }
    constructor(message: string, options?: { response?: { status: number } }) {
      super(message)
      this.response = options?.response ?? { status: 500 }
    }
  }

  const kyFn = vi.fn()

  const mockKy = Object.assign(kyFn, {
    create: (config: { hooks?: MockKyHooks }) => {
      capturedHooks = config.hooks ?? null
      return { get: vi.fn(), post: mockKyPost, put: vi.fn(), delete: vi.fn() }
    },
    post: mockKyPost,
    HTTPError,
  })

  return { default: mockKy, HTTPError }
})

// We need to manage localStorage for CSRF tests
const storage = new Map<string, string>()
const mockLocalStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
  clear: () => storage.clear(),
  get length() { return storage.size },
  key: (index: number) => [...storage.keys()][index] ?? null,
}

Object.defineProperty(window, 'localStorage', { value: mockLocalStorage, writable: true })

// Import to trigger module execution which calls ky.create
await import('@/api/client')

describe('client CSRF hooks', () => {
  beforeEach(() => {
    storage.clear()
    mockKyPost.mockReset()
  })

  it('captured hooks from ky.create', () => {
    expect(capturedHooks).not.toBeNull()
    expect(capturedHooks!.beforeRequest).toHaveLength(1)
    expect(capturedHooks!.afterResponse).toHaveLength(1)
  })

  describe('beforeRequest hook', () => {
    it('sets CSRF header for POST requests when token exists', async () => {
      // Simulate a prior response that delivered a CSRF token via afterResponse hook
      const priorRequest = new Request('https://example.com/api/auth/login', { method: 'POST' })
      const priorResponse = new Response('', {
        status: 200,
        headers: { 'X-CSRF-Token': 'test-token' },
      })
      await capturedHooks!.afterResponse[0](priorRequest, {}, priorResponse)

      // Now verify beforeRequest adds the token to subsequent POST requests
      const request = new Request('https://example.com/api/posts', {
        method: 'POST',
      })

      capturedHooks!.beforeRequest[0](request)

      expect(request.headers.get('X-CSRF-Token')).toBe('test-token')
    })

    it('does not set CSRF header for GET requests', () => {
      const headers = new Headers()
      const request = new Request('https://example.com/api/posts', {
        method: 'GET',
        headers,
      })

      capturedHooks!.beforeRequest[0](request)

      expect(request.headers.get('X-CSRF-Token')).toBeNull()
    })
  })

  describe('afterResponse hook', () => {
    it('persists CSRF token from response header', async () => {
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('', {
        status: 200,
        headers: { 'X-CSRF-Token': 'new-token' },
      })

      await capturedHooks!.afterResponse[0](request, {}, response)

      expect(storage.get('agb_csrf_token')).toBe('new-token')
    })

    it('clears token when empty response header', async () => {
      storage.set('agb_csrf_token', 'old-token')
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('', {
        status: 200,
        headers: { 'X-CSRF-Token': '' },
      })

      await capturedHooks!.afterResponse[0](request, {}, response)

      expect(storage.get('agb_csrf_token')).toBeUndefined()
    })

    it('does not update token when no CSRF header in response', async () => {
      storage.set('agb_csrf_token', 'existing')
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('', { status: 200 })

      await capturedHooks!.afterResponse[0](request, {}, response)

      expect(storage.get('agb_csrf_token')).toBe('existing')
    })

    it('attempts refresh on 401 response', async () => {
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('', { status: 401 })
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      // The afterResponse hook will try to refresh and may fail since ky.post is mocked
      mockKyPost.mockRejectedValue(new Error('refresh failed'))

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      // Should return original response when refresh fails
      expect(result.status).toBe(401)
      consoleSpy.mockRestore()
    })

    it('does not retry already-retried requests', async () => {
      const headers = new Headers({ 'X-Auth-Retry': '1' })
      const request = new Request('https://example.com/api/posts', { method: 'GET', headers })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      // Should not have attempted refresh
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('does not retry auth refresh endpoint', async () => {
      const request = new Request('https://example.com/api/auth/refresh', { method: 'POST' })
      const response = new Response('', { status: 401 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(401)
      expect(mockKyPost).not.toHaveBeenCalled()
    })

    it('returns success response for non-401', async () => {
      const request = new Request('https://example.com/api/posts', { method: 'GET' })
      const response = new Response('ok', { status: 200 })

      const result = await capturedHooks!.afterResponse[0](request, {}, response)

      expect(result.status).toBe(200)
    })
  })
})
