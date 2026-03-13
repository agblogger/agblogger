import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { CrossPostResult, SocialAccount } from '@/api/crosspost'
import { MockHTTPError } from '@/test/MockHTTPError'

const mockFetchCrossPostHistory = vi.fn()
const mockFetchSocialAccounts = vi.fn()

vi.mock('@/api/crosspost', () => ({
  fetchCrossPostHistory: (...args: unknown[]) => mockFetchCrossPostHistory(...args) as unknown,
  fetchSocialAccounts: (...args: unknown[]) => mockFetchSocialAccounts(...args) as unknown,
}))

vi.mock('@/components/crosspost/CrossPostDialog', () => ({
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? (
      <div data-testid="crosspost-dialog">
        <button onClick={onClose}>Close dialog</button>
      </div>
    ) : null,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { HTTPError: MockHTTPError }
})

vi.mock('@/components/crosspost/CrossPostHistory', () => ({
  default: ({ items, loading }: { items: CrossPostResult[]; loading: boolean }) => (
    <div data-testid="crosspost-history">
      {loading && <span>Loading history...</span>}
      {items.map((item) => (
        <span key={item.id}>{item.platform}</span>
      ))}
    </div>
  ),
}))

import CrossPostSection from '../CrossPostSection'

const mockPost = {
  id: 1,
  file_path: 'posts/test.md',
  title: 'Test Post',
  author: 'admin',
  created_at: '2026-01-01T00:00:00Z',
  modified_at: '2026-01-01T00:00:00Z',
  is_draft: false,
  rendered_excerpt: null,
  rendered_html: '<p>Test</p>',
  content: '# Test',
  labels: ['#swe'],
}

const mockAccounts: SocialAccount[] = [
  { id: 1, platform: 'bluesky', account_name: '@user.bsky.social', created_at: '2026-01-01' },
]

const mockHistory: CrossPostResult[] = [
  {
    id: 1,
    post_path: 'posts/test.md',
    platform: 'bluesky',
    platform_id: '123',
    status: 'posted',
    posted_at: '2026-01-01T00:00:00Z',
    error: null,
  },
]

describe('CrossPostSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders section heading', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    // Wait for async effects to settle
    await waitFor(() => {
      expect(mockFetchCrossPostHistory).toHaveBeenCalled()
    })
    expect(screen.getByText('Cross-posting')).toBeInTheDocument()
  })

  it('shows Share button when accounts are available', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('Cross-post')).toBeInTheDocument()
    })
  })

  it('shows a connect-account hint when no accounts are available', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByTestId('crosspost-history')).toBeInTheDocument()
    })
    expect(screen.queryByText('Cross-post')).not.toBeInTheDocument()
    expect(
      screen.getByText('Connect a social account in Admin > Social to cross-post this post.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Connect social account' })).toHaveAttribute(
      'href',
      '/admin?tab=social',
    )
  })

  it('displays history items', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: mockHistory })
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('bluesky')).toBeInTheDocument()
    })
  })

  it('opens dialog when Cross-post is clicked', async () => {
    const user = userEvent.setup()
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('Cross-post')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Cross-post'))

    expect(screen.getByTestId('crosspost-dialog')).toBeInTheDocument()
  })

  it('closes dialog and reloads history', async () => {
    const user = userEvent.setup()
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('Cross-post')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Cross-post'))
    expect(screen.getByTestId('crosspost-dialog')).toBeInTheDocument()

    // Close the dialog
    await user.click(screen.getByText('Close dialog'))

    await waitFor(() => {
      expect(screen.queryByTestId('crosspost-dialog')).not.toBeInTheDocument()
    })
    // History is reloaded on close (initial load + close reload)
    expect(mockFetchCrossPostHistory.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('shows a history error when history fetch fails', async () => {
    mockFetchCrossPostHistory.mockRejectedValue(new Error('Network error'))
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load cross-post history. Please try again.'),
      ).toBeInTheDocument()
    })
  })

  it('shows an accounts error when social accounts fetch fails', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockRejectedValue(new Error('Network error'))

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load connected social accounts. Please try again.'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText('Cross-post')).not.toBeInTheDocument()
  })

  it('shows session expired when history fetch returns 401', async () => {
    mockFetchCrossPostHistory.mockRejectedValue(new MockHTTPError(401))
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows session expired when accounts fetch returns 401', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockRejectedValue(new MockHTTPError(401))

    render(<MemoryRouter><CrossPostSection filePath="posts/test.md" post={mockPost} /></MemoryRouter>)

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('disables cross-posting for draft posts', () => {
    render(
      <MemoryRouter>
        <CrossPostSection
          filePath="posts/test.md"
          post={{ ...mockPost, is_draft: true }}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Publish this draft to enable cross-posting.')).toBeInTheDocument()
    expect(screen.queryByText('Cross-post')).not.toBeInTheDocument()
    expect(mockFetchCrossPostHistory).not.toHaveBeenCalled()
    expect(mockFetchSocialAccounts).not.toHaveBeenCalled()
  })
})
