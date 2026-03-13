import { describe, it, expect, vi } from 'vitest'

import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    HTTPError: MockHTTPError,
  }
})

import { parseErrorDetail, extractErrorDetail } from '../parseError'

describe('parseErrorDetail', () => {
  it('returns string detail from response body', async () => {
    const response = mockResponse(JSON.stringify({ detail: 'Invalid date format' }))
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('Invalid date format')
  })

  it('returns fallback for empty string detail', async () => {
    const response = mockResponse(JSON.stringify({ detail: '' }))
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('fallback')
  })

  it('returns first message from array detail', async () => {
    const response = mockResponse(
      JSON.stringify({ detail: [{ msg: 'validation error' }] }),
    )
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('validation error')
  })

  it('returns field-prefixed messages from array detail', async () => {
    const response = mockResponse(
      JSON.stringify({
        detail: [
          { field: 'title', message: 'String should have at least 1 character' },
        ],
      }),
    )
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('Title: String should have at least 1 character')
  })

  it('joins multiple array detail items', async () => {
    const response = mockResponse(
      JSON.stringify({
        detail: [
          { field: 'title', message: 'Too short' },
          { field: 'body', message: 'Required' },
        ],
      }),
    )
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('Title: Too short, Body: Required')
  })

  it('prefers message over msg in array items', async () => {
    const response = mockResponse(
      JSON.stringify({ detail: [{ message: 'preferred', msg: 'fallback' }] }),
    )
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('preferred')
  })

  it('returns fallback for non-object detail', async () => {
    const response = mockResponse(JSON.stringify({ detail: 42 }))
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('fallback')
  })

  it('returns fallback for missing detail field', async () => {
    const response = mockResponse(JSON.stringify({ error: 'something' }))
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('fallback')
  })

  it('returns fallback for invalid JSON', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const response = mockResponse('not json')
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('fallback')
    warnSpy.mockRestore()
  })

  it('returns fallback for empty array detail', async () => {
    const response = mockResponse(JSON.stringify({ detail: [] }))
    const result = await parseErrorDetail(response, 'fallback')
    expect(result).toBe('fallback')
  })

  it('logs a console.warn when response parsing fails', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const response = mockResponse('not json')
    await parseErrorDetail(response, 'fallback')
    expect(warnSpy).toHaveBeenCalledOnce()
    expect(warnSpy).toHaveBeenCalledWith(
      'parseErrorDetail: failed to parse error response',
      expect.any(SyntaxError),
    )
    warnSpy.mockRestore()
  })
})

describe('extractErrorDetail', () => {
  it('returns session expired message for 401 HTTPError', async () => {
    const err = new MockHTTPError(401)
    const result = await extractErrorDetail(err, 'fallback')
    expect(result).toBe('Session expired. Please log in again.')
  })

  it('returns fallback for 500 HTTPError without parsing body', async () => {
    const err = new MockHTTPError(500, JSON.stringify({ detail: 'Internal: pool exhausted' }))
    const result = await extractErrorDetail(err, 'Server error')
    expect(result).toBe('Server error')
  })

  it('returns fallback for 503 HTTPError', async () => {
    const err = new MockHTTPError(503, JSON.stringify({ detail: 'Service unavailable' }))
    const result = await extractErrorDetail(err, 'Server error')
    expect(result).toBe('Server error')
  })

  it('parses error detail for 4xx HTTPError', async () => {
    const err = new MockHTTPError(422, JSON.stringify({ detail: 'Validation failed' }))
    const result = await extractErrorDetail(err, 'fallback')
    expect(result).toBe('Validation failed')
  })

  it('returns fallback for non-HTTPError', async () => {
    const err = new Error('network error')
    const result = await extractErrorDetail(err, 'fallback')
    expect(result).toBe('fallback')
  })

  it('returns fallback for non-Error value', async () => {
    const result = await extractErrorDetail('string error', 'fallback')
    expect(result).toBe('fallback')
  })
})

function mockResponse(body: string): { text: () => Promise<string> } {
  return { text: () => Promise.resolve(body) }
}
