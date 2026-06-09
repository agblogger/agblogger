import { renderHook, waitFor, act } from '@testing-library/react'
import { createRef } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import api from '@/api/client'
import { useMarkdownPreview } from '../useMarkdownPreview'

vi.mock('@/api/client', () => ({ default: { post: vi.fn() } }))
// KaTeX + code-enhance are exercised elsewhere; isolate the fetch/debounce logic.
vi.mock('@/hooks/useKatex', () => ({ useRenderedHtml: (h: string | null) => h ?? '' }))
vi.mock('@/hooks/useCodeBlockEnhance', () => ({ useCodeBlockEnhance: () => {} }))

const mockPost = vi.mocked(api.post)

function mockRender(html: string) {
  return { json: () => Promise.resolve({ html }) } as unknown as ReturnType<typeof api.post>
}

beforeEach(() => {
  vi.useFakeTimers()
  mockPost.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('useMarkdownPreview', () => {
  it('returns no content and does not fetch for empty/whitespace input', () => {
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() =>
      useMarkdownPreview({ value: '   ', previewRef: ref }),
    )
    expect(result.current.hasContent).toBe(false)
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('debounces, then fetches and returns rendered html', async () => {
    mockPost.mockReturnValue(mockRender('<p>hi</p>'))
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() =>
      useMarkdownPreview({ value: 'hi', previewRef: ref, debounceMs: 500 }),
    )
    expect(mockPost).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.html).toBe('<p>hi</p>'))
    expect(result.current.error).toBe(false)
    expect(mockPost).toHaveBeenCalledWith('render/preview', { json: { markdown: 'hi' } })
  })

  it('includes file_path in the payload when provided', async () => {
    mockPost.mockReturnValue(mockRender('<p>x</p>'))
    const ref = createRef<HTMLDivElement>()
    renderHook(() =>
      useMarkdownPreview({ value: 'x', filePath: 'posts/a/index.md', previewRef: ref }),
    )
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('render/preview', {
        json: { markdown: 'x', file_path: 'posts/a/index.md' },
      }),
    )
  })

  it('sets error=true when the render call rejects', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockPost.mockReturnValue({ json: () => Promise.reject(new Error('boom')) } as never)
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() => useMarkdownPreview({ value: 'x', previewRef: ref }))
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.error).toBe(true))
  })

  it('ignores a stale response when a newer request supersedes it', async () => {
    let resolveFirst: (v: { html: string }) => void = () => {}
    const first = { json: () => new Promise<{ html: string }>((r) => (resolveFirst = r)) }
    mockPost.mockReturnValueOnce(first as never)
    mockPost.mockReturnValueOnce(mockRender('<p>second</p>'))

    const ref = createRef<HTMLDivElement>()
    const { result, rerender } = renderHook(
      ({ value }) => useMarkdownPreview({ value, previewRef: ref }),
      { initialProps: { value: 'one' } },
    )
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    rerender({ value: 'two' })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.html).toBe('<p>second</p>'))

    // Late resolution of the first (stale) request must not overwrite the html.
    await act(async () => {
      resolveFirst({ html: '<p>first</p>' })
    })
    expect(result.current.html).toBe('<p>second</p>')
  })
})
