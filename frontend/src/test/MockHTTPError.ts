/**
 * Shared MockHTTPError class for use in test files that mock `@/api/client`.
 *
 * Mirrors the shape of ky's HTTPError so that production code using
 * `instanceof HTTPError` works correctly when the mock module maps
 * `HTTPError` to this class.
 */
export class MockHTTPError extends Error {
  response: {
    status: number
    text: () => Promise<string>
    json: () => Promise<unknown>
  }

  constructor(status: number, body?: string) {
    super(`HTTP ${status}`)
    const bodyStr = body ?? ''
    this.response = {
      status,
      text: () => Promise.resolve(bodyStr),
      json: () => {
        try {
          return Promise.resolve(JSON.parse(bodyStr || '{}'))
        } catch {
          return Promise.reject(new SyntaxError('Failed to parse response body as JSON'))
        }
      },
    }
  }
}

/** Alias so tests that import `HTTPError` by name work unchanged. */
export { MockHTTPError as HTTPError }
