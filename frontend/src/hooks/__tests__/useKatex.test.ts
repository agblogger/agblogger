import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

const sanitizeSpy = vi.fn((html: string) => html)
vi.mock('dompurify', () => ({
  default: { sanitize: sanitizeSpy },
}))

vi.mock('katex', () => ({
  default: {
    renderToString: (tex: string, opts: { displayMode?: boolean; throwOnError?: boolean }) => {
      const mode = opts.displayMode ? 'display' : 'inline'
      return `<rendered-${mode}>${tex}</rendered-${mode}>`
    },
  },
}))

vi.mock('katex/dist/katex.min.css', () => ({}))

// Must import after mock
const { useRenderedHtml } = await import('@/hooks/useKatex')

describe('useRenderedHtml', () => {
  beforeEach(() => {
    sanitizeSpy.mockClear()
  })

  it('returns empty string for null', () => {
    const { result } = renderHook(() => useRenderedHtml(null))
    expect(result.current).toBe('')
  })

  it('returns empty string for undefined', () => {
    const { result } = renderHook(() => useRenderedHtml(undefined))
    expect(result.current).toBe('')
  })

  it('passes through HTML without math spans', () => {
    const html = '<p>Hello world</p>'
    const { result } = renderHook(() => useRenderedHtml(html))
    expect(result.current).toBe('<p>Hello world</p>')
  })

  it('returns raw HTML without math unchanged (no katex needed)', () => {
    const { result } = renderHook(() => useRenderedHtml('<p>No math here</p>'))
    expect(result.current).toBe('<p>No math here</p>')
  })

  it('renders inline math spans', async () => {
    const html = '<p>The value <span class="math inline">x^2</span> is positive.</p>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toBe(
        '<p>The value <span class="math inline"><rendered-inline>x^2</rendered-inline></span> is positive.</p>',
      )
    })
  })

  it('renders display math spans with displayMode', async () => {
    const html = '<span class="math display">\\sum_{i=0}^n i</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toBe(
        '<span class="math display"><rendered-display>\\sum_{i=0}^n i</rendered-display></span>',
      )
    })
  })

  it('handles multiple math spans', async () => {
    const html = '<span class="math inline">a</span> and <span class="math display">b</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toContain('<rendered-inline>a</rendered-inline>')
      expect(result.current).toContain('<rendered-display>b</rendered-display>')
    })
  })

  it('trims whitespace from tex content', async () => {
    const html = '<span class="math inline"> x + 1 </span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toContain('<rendered-inline>x + 1</rendered-inline>')
    })
  })

  it('decodes HTML entities in math content', async () => {
    // Regression: matrix &amp; was passed literally to KaTeX instead of &
    const html =
      '<span class="math display">\\begin{pmatrix} a &amp; b \\\\ c &amp; d \\end{pmatrix}</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      // The mock renders tex directly, so we can check & is decoded
      expect(result.current).toContain(
        '\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}',
      )
      expect(result.current).not.toContain('&amp;')
    })
  })

  it('decodes &lt; and &gt; in math content', async () => {
    const html = '<span class="math inline">a &lt; b &gt; c</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toContain('a < b > c')
    })
  })

  it('decodes &quot; in math content', async () => {
    const html = '<span class="math inline">&quot;text&quot;</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toContain('"text"')
    })
  })

  it('sanitizes HTML without math through DOMPurify', () => {
    const html = '<p>Hello</p>'
    renderHook(() => useRenderedHtml(html))
    expect(sanitizeSpy).toHaveBeenCalledWith(html)
  })

  it('sanitizes KaTeX-rendered HTML through DOMPurify', async () => {
    const html = '<span class="math inline">x</span>'
    const { result } = renderHook(() => useRenderedHtml(html))
    await waitFor(() => {
      expect(result.current).toContain('<rendered-inline>')
    })
    expect(sanitizeSpy).toHaveBeenCalledWith(
      expect.stringContaining('<rendered-inline>'),
    )
  })
})
