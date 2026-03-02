import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { CrossPostResult, SocialAccount } from '@/api/crosspost'

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

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    // Wait for async effects to settle
    await waitFor(() => {
      expect(mockFetchCrossPostHistory).toHaveBeenCalled()
    })
    expect(screen.getByText('Cross-posting')).toBeInTheDocument()
  })

  it('shows Share button when accounts are available', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    await waitFor(() => {
      expect(screen.getByText('Share')).toBeInTheDocument()
    })
  })

  it('hides Share button when no accounts', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    await waitFor(() => {
      expect(screen.getByTestId('crosspost-history')).toBeInTheDocument()
    })
    expect(screen.queryByText('Share')).not.toBeInTheDocument()
  })

  it('displays history items', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: mockHistory })
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    await waitFor(() => {
      expect(screen.getByText('bluesky')).toBeInTheDocument()
    })
  })

  it('opens dialog when Share is clicked', async () => {
    const user = userEvent.setup()
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    await waitFor(() => {
      expect(screen.getByText('Share')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Share'))

    expect(screen.getByTestId('crosspost-dialog')).toBeInTheDocument()
  })

  it('closes dialog and reloads history', async () => {
    const user = userEvent.setup()
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockResolvedValue(mockAccounts)

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    await waitFor(() => {
      expect(screen.getByText('Share')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Share'))
    expect(screen.getByTestId('crosspost-dialog')).toBeInTheDocument()

    // Close the dialog
    await user.click(screen.getByText('Close dialog'))

    await waitFor(() => {
      expect(screen.queryByTestId('crosspost-dialog')).not.toBeInTheDocument()
    })
    // History is reloaded on close (initial load + close reload)
    expect(mockFetchCrossPostHistory.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('handles history fetch failure gracefully', async () => {
    mockFetchCrossPostHistory.mockRejectedValue(new Error('Network error'))
    mockFetchSocialAccounts.mockResolvedValue([])

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    // Should still render the section without crashing
    await waitFor(() => {
      expect(screen.getByText('Cross-posting')).toBeInTheDocument()
    })
  })

  it('handles accounts fetch failure gracefully', async () => {
    mockFetchCrossPostHistory.mockResolvedValue({ items: [] })
    mockFetchSocialAccounts.mockRejectedValue(new Error('Network error'))

    render(<CrossPostSection filePath="posts/test.md" post={mockPost} />)

    // Should still render the section without crashing
    await waitFor(() => {
      expect(screen.getByText('Cross-posting')).toBeInTheDocument()
    })
    // No Share button since accounts fetch failed
    expect(screen.queryByText('Share')).not.toBeInTheDocument()
  })
})
