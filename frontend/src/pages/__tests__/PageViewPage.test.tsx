import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

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
  return render(createElement(RouterProvider, { router }))
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

  it('strips first h1 from rendered HTML', async () => {
    mockApiGet.mockResolvedValue({
      id: 'about',
      title: 'About Us',
      rendered_html: '<h1>About Us</h1><p>Content here.</p>',
    })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Content here.')).toBeInTheDocument()
    })
    // The h1 "About Us" inside the content should be stripped (only the title header remains)
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toHaveTextContent('About Us')
  })

  it('shows "Page not found" when page is null', async () => {
    mockApiGet.mockRejectedValue(new Error('fail'))
    renderPage('nonexistent')

    await waitFor(() => {
      expect(screen.getByText('Failed to load page.')).toBeInTheDocument()
    })
  })
})
