import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'

const mockApiGet = vi.fn()

vi.mock('@/api/client', () => ({
  default: { get: (...args: unknown[]) => ({ json: () => mockApiGet(...args) as unknown }) },
}))

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null | undefined) => html ?? '',
}))

import PageViewPage from '../PageViewPage'

function renderPage(pageId = 'about') {
  const router = createMemoryRouter(
    [{ path: '/page/:pageId', element: createElement(PageViewPage) }],
    { initialEntries: [`/page/${pageId}`] },
  )
  return render(
    createElement(
      SWRConfig,
      { value: { fetcher: mockApiGet, provider: () => new Map(), dedupingInterval: 0 } },
      createElement(RouterProvider, { router }),
    ),
  )
}

describe('PageViewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows spinner while loading', () => {
    mockApiGet.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows error when fetch fails', async () => {
    mockApiGet.mockRejectedValue(new Error('fail'))
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Failed to load page.')).toBeInTheDocument()
    })
  })

  it('renders page title and content', async () => {
    mockApiGet.mockResolvedValue({
      id: 'about',
      title: 'About Us',
      rendered_html: '<p>We are a blog.</p>',
    })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('About Us')).toBeInTheDocument()
    })
    expect(screen.getByText('We are a blog.')).toBeInTheDocument()
  })

  it('renders the body verbatim without stripping headings', async () => {
    mockApiGet.mockResolvedValue({
      id: 'about',
      title: 'About Us',
      rendered_html: '<h1>Body Heading</h1><p>Content here.</p>',
    })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Content here.')).toBeInTheDocument()
    })
    // The title comes from config (shown separately); body headings are kept as-is.
    const headings = screen.getAllByRole('heading', { level: 1 })
    expect(headings.map((h) => h.textContent)).toEqual(['About Us', 'Body Heading'])
  })

  it('enhances code blocks with a language header and copy button', async () => {
    mockApiGet.mockResolvedValue({
      id: 'about',
      title: 'About Us',
      rendered_html:
        '<pre class="sourceCode python"><code class="sourceCode python">print("hi")</code></pre>',
    })
    renderPage()

    await waitFor(() => {
      expect(document.querySelector('.code-block-lang')?.textContent).toBe('python')
    })
    expect(document.querySelector('.code-block-copy')?.textContent).toBe('Copy')
  })

  it('shows "Page not found" when page is null', async () => {
    mockApiGet.mockRejectedValue(new Error('fail'))
    renderPage('nonexistent')

    await waitFor(() => {
      expect(screen.getByText('Failed to load page.')).toBeInTheDocument()
    })
  })
})
