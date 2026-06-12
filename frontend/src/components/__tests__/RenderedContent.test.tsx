import { createElement, createRef } from 'react'
import { render, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null | undefined) => html ?? '',
}))

import RenderedContent from '../RenderedContent'

describe('RenderedContent', () => {
  it('enhances code blocks with a language header and copy button', async () => {
    const { container } = render(
      createElement(RenderedContent, {
        html: '<pre class="sourceCode python"><code class="sourceCode python">print("hi")</code></pre>',
      }),
    )

    await waitFor(() => {
      expect(container.querySelector('.code-block-lang')?.textContent).toBe('python')
    })
    expect(container.querySelector('.code-block-copy')?.textContent).toBe('Copy')
  })

  it('renders body HTML unchanged by default', () => {
    const { container } = render(
      createElement(RenderedContent, { html: '<h1>Title</h1><p>Body.</p>' }),
    )

    expect(container.querySelector('h1')?.textContent).toBe('Title')
    expect(container.querySelector('p')?.textContent).toBe('Body.')
  })

  it('exposes the content element through an external ref', () => {
    const ref = createRef<HTMLDivElement>()
    render(createElement(RenderedContent, { html: '<p>Body.</p>', contentRef: ref }))

    expect(ref.current).not.toBeNull()
    expect(ref.current?.querySelector('p')?.textContent).toBe('Body.')
  })
})
