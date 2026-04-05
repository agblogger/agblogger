import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'
import type { PathHit } from '@/api/client'

const mockFetchPathReferrers = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
}))

import TopPagesPanel from '../TopPagesPanel'

const DEFAULT_PATHS: PathHit[] = [
  { path_id: 1, path: '/posts/hello', views: 800 },
  { path_id: 2, path: '/posts/world', views: 434 },
]

function renderPanel(paths: PathHit[] = DEFAULT_PATHS) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <TopPagesPanel paths={paths} />
    </SWRConfig>,
  )
}

describe('TopPagesPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchPathReferrers.mockResolvedValue({ path_id: 0, referrers: [] })
  })

  it('renders "Top pages" heading', () => {
    renderPanel()
    expect(screen.getByText('Top pages')).toBeInTheDocument()
  })

  it('renders paths sorted by views descending', () => {
    renderPanel([
      { path_id: 3, path: '/low', views: 10 },
      { path_id: 1, path: '/high', views: 900 },
      { path_id: 2, path: '/mid', views: 300 },
    ])
    const rows = screen.getAllByRole('button', { name: /View referrers for/ })
    expect(rows[0]).toHaveAttribute('aria-label', 'View referrers for /high')
    expect(rows[1]).toHaveAttribute('aria-label', 'View referrers for /mid')
    expect(rows[2]).toHaveAttribute('aria-label', 'View referrers for /low')
  })

  it('shows empty state when paths is empty', () => {
    renderPanel([])
    expect(screen.getByText('No page data for selected range.')).toBeInTheDocument()
  })

  it('expands inline referrer detail on row click', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 1,
      referrers: [
        { referrer: 'https://example.com', count: 42 },
      ],
    })
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('https://example.com')).toBeInTheDocument()
    })
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('collapses referrer row when same row is clicked again', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 1,
      referrers: [{ referrer: 'https://example.com', count: 10 }],
    })
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))
    await waitFor(() => {
      expect(screen.getByText('https://example.com')).toBeInTheDocument()
    })

    // Click same row again
    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))
    expect(screen.queryByText('https://example.com')).not.toBeInTheDocument()
  })

  it('shows loading spinner while referrers load', async () => {
    // Never resolves
    mockFetchPathReferrers.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByRole('status', { name: /Loading referrers/i })).toBeInTheDocument()
    })
  })

  it('shows error message when referrer fetch fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchPathReferrers.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('Failed to load referrers. Please try again.')).toBeInTheDocument()
    })
  })

  it('shows "No referrers" when referrer list is empty', async () => {
    mockFetchPathReferrers.mockResolvedValue({ path_id: 1, referrers: [] })
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('No referrers')).toBeInTheDocument()
    })
  })
})
