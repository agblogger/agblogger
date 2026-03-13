import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { SocialAccount } from '@/api/crosspost'
import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { HTTPError: MockHTTPError }
})

import CrossPostDialog from '../CrossPostDialog'

const mockCrossPost = vi.fn()

vi.mock('@/api/crosspost', () => ({
  crossPost: (...args: unknown[]) => mockCrossPost(...args) as unknown,
}))

const blueskyAccount: SocialAccount = {
  id: 1,
  platform: 'bluesky',
  account_name: 'alice.bsky.social',
  created_at: '2026-01-15T10:00:00Z',
}

const mastodonAccount: SocialAccount = {
  id: 2,
  platform: 'mastodon',
  account_name: '@alice@mastodon.social',
  created_at: '2026-01-16T10:00:00Z',
}

const xAccount: SocialAccount = {
  id: 3,
  platform: 'x',
  account_name: '@alice_x',
  created_at: '2026-01-17T10:00:00Z',
}

const facebookAccount: SocialAccount = {
  id: 4,
  platform: 'facebook',
  account_name: 'My Page',
  created_at: '2026-01-18T10:00:00Z',
}

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  accounts: [blueskyAccount, mastodonAccount],
  postPath: 'posts/2026-02-20-hello-world/index.md',
  postTitle: 'Hello World',
  postExcerpt: 'This is a test post excerpt.',
  postLabels: ['swe', 'typescript'],
}

function renderDialog(
  overrides: Partial<typeof defaultProps> & { initialPlatforms?: string[] } = {},
) {
  const props = { ...defaultProps, ...overrides }
  return render(<CrossPostDialog {...props} />)
}

describe('CrossPostDialog', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('does not render when open is false', () => {
    renderDialog({ open: false })
    expect(screen.queryByText('Cross-post')).not.toBeInTheDocument()
  })

  it('renders platform checkboxes for connected accounts', () => {
    renderDialog()
    expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    expect(screen.getByText('@alice@mastodon.social')).toBeInTheDocument()
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes[0]).toBeChecked()
    expect(checkboxes[1]).toBeChecked()
  })

  it('shows character count per selected platform', () => {
    renderDialog()
    // Both platforms should show character counts since both are checked by default
    expect(screen.getByText(/\/300/)).toBeInTheDocument()
    expect(screen.getByText(/\/500/)).toBeInTheDocument()
  })

  it('disables cross-post button when over character limit', async () => {
    const user = userEvent.setup()
    renderDialog({ accounts: [blueskyAccount] })

    const textarea = screen.getByLabelText('Cross-post text')
    // Clear existing text and type text over 300 characters
    await user.clear(textarea)
    const longText = 'a'.repeat(301)
    await user.type(textarea, longText)

    const postButton = screen.getByRole('button', { name: 'Cross-post' })
    expect(postButton).toBeDisabled()

    // Counter's parent container should be red
    const counter = screen.getByText(`${longText.length}/300`)
    expect(counter.closest('div')).toHaveClass('text-red-600')
  })

  it('disables cross-post button when no platforms selected', async () => {
    const user = userEvent.setup()
    renderDialog()

    // Uncheck all platforms
    const checkboxes = screen.getAllByRole('checkbox')
    for (const checkbox of checkboxes) {
      await user.click(checkbox)
    }

    const postButton = screen.getByRole('button', { name: 'Cross-post' })
    expect(postButton).toBeDisabled()
  })

  it('calls crossPost with selected platforms and custom text on submit', async () => {
    mockCrossPost.mockResolvedValue([
      {
        id: 1,
        post_path: defaultProps.postPath,
        platform: 'bluesky',
        platform_id: '123',
        status: 'posted',
        posted_at: '2026-02-20T10:00:00Z',
        error: null,
      },
    ])

    const user = userEvent.setup()
    renderDialog({ accounts: [blueskyAccount] })

    const textarea = screen.getByLabelText('Cross-post text')
    await user.clear(textarea)
    await user.type(textarea, 'Custom post text')

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    await waitFor(() => {
      expect(mockCrossPost).toHaveBeenCalledWith(
        defaultProps.postPath,
        ['bluesky'],
        'Custom post text',
      )
    })
  })

  it('shows results after successful posting', async () => {
    mockCrossPost.mockResolvedValue([
      {
        id: 1,
        post_path: defaultProps.postPath,
        platform: 'bluesky',
        platform_id: '123',
        status: 'posted',
        posted_at: '2026-02-20T10:00:00Z',
        error: null,
      },
      {
        id: 2,
        post_path: defaultProps.postPath,
        platform: 'mastodon',
        platform_id: null,
        status: 'failed',
        posted_at: null,
        error: 'Rate limited',
      },
    ])

    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    await waitFor(() => {
      expect(screen.getByText('Cross-post results')).toBeInTheDocument()
    })

    expect(screen.getByText('Posted')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('Rate limited')).toBeInTheDocument()

    // Should have Close button in results view
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('shows session expired when cross-post returns 401', async () => {
    mockCrossPost.mockRejectedValue(new MockHTTPError(401))

    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows parsed error detail for non-401 HTTP errors', async () => {
    mockCrossPost.mockRejectedValue(
      new MockHTTPError(422, JSON.stringify({ detail: 'Post content is empty' })),
    )

    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    await waitFor(() => {
      expect(screen.getByText('Post content is empty')).toBeInTheDocument()
    })
  })

  it('shows generic error for non-HTTP failures', async () => {
    mockCrossPost.mockRejectedValue(new Error('Network error'))

    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to cross-post. The server may be unavailable.'),
      ).toBeInTheDocument()
    })
  })

  it('pre-checks only initialPlatforms when provided', () => {
    renderDialog({ initialPlatforms: ['bluesky'] })

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[0]).toBeChecked() // bluesky
    expect(checkboxes[1]).not.toBeChecked() // mastodon
  })

  it('generates default text with excerpt, hashtags, and URL', () => {
    renderDialog()

    const textarea = screen.getByLabelText('Cross-post text')
    const value = (textarea as HTMLTextAreaElement).value
    expect(value).toContain('This is a test post excerpt.')
    expect(value).toContain('#swe')
    expect(value).toContain('#typescript')
    expect(value).toContain('/post/2026-02-20-hello-world')
  })

  it('uses postTitle when postExcerpt is empty', () => {
    renderDialog({ postExcerpt: '' })

    const textarea = screen.getByLabelText('Cross-post text')
    const value = (textarea as HTMLTextAreaElement).value
    expect(value).toContain('Hello World')
    expect(value).not.toContain('This is a test post excerpt.')
  })

  it('hides character counter when platform is unchecked', async () => {
    const user = userEvent.setup()
    renderDialog({ accounts: [blueskyAccount] })

    expect(screen.getByText(/\/300/)).toBeInTheDocument()

    // Uncheck bluesky
    await user.click(screen.getByRole('checkbox'))

    expect(screen.queryByText(/\/300/)).not.toBeInTheDocument()
  })

  it('calls onClose when Cancel button is clicked', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onClose })

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not reset user-edited text when accounts array reference changes', async () => {
    const user = userEvent.setup()
    const accounts = [blueskyAccount]
    const { rerender } = render(
      <CrossPostDialog
        {...defaultProps}
        accounts={accounts}
        open={true}
      />,
    )

    const textarea = screen.getByLabelText('Cross-post text')
    await user.clear(textarea)
    await user.type(textarea, 'My custom text')

    // Re-render with a new accounts array reference (same content)
    rerender(
      <CrossPostDialog
        {...defaultProps}
        accounts={[{ ...blueskyAccount }]}
        open={true}
      />,
    )

    // User-edited text should be preserved
    expect(screen.getByLabelText('Cross-post text')).toHaveValue('My custom text')
  })

  it('disables controls while posting', async () => {
    let resolvePost: (value: unknown) => void
    mockCrossPost.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve
      }),
    )

    const user = userEvent.setup()
    renderDialog({ accounts: [blueskyAccount] })

    await user.click(screen.getByRole('button', { name: 'Cross-post' }))

    // While posting, controls should be disabled
    expect(screen.getByLabelText('Cross-post text')).toBeDisabled()
    expect(screen.getByRole('checkbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cross-posting...' })).toBeDisabled()

    // Resolve to clean up
    resolvePost!([])
    await waitFor(() => {
      expect(screen.getByText('Cross-post results')).toBeInTheDocument()
    })
  })

  it('shows X character counter with 280 limit', () => {
    renderDialog({ accounts: [xAccount] })
    expect(screen.getByText(/\/280/)).toBeInTheDocument()
  })

  it('disables post when X text exceeds 280 characters', async () => {
    const user = userEvent.setup()
    renderDialog({ accounts: [xAccount] })

    const textarea = screen.getByLabelText('Cross-post text')
    await user.clear(textarea)
    const longText = 'a'.repeat(281)
    await user.type(textarea, longText)

    const postButton = screen.getByRole('button', { name: 'Cross-post' })
    expect(postButton).toBeDisabled()

    const counter = screen.getByText(`${longText.length}/280`)
    expect(counter.closest('div')).toHaveClass('text-red-600')
  })

  it('does not show character counter for Facebook (no limit)', () => {
    renderDialog({ accounts: [facebookAccount] })
    // Facebook has no character limit, so no /300 or /280 or /500 counter
    expect(screen.queryByText(/\/300/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\/280/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\/500/)).not.toBeInTheDocument()
  })

  it('renders all four platform checkboxes when all accounts provided', () => {
    renderDialog({ accounts: [blueskyAccount, mastodonAccount, xAccount, facebookAccount] })
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(4)
    expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    expect(screen.getByText('@alice@mastodon.social')).toBeInTheDocument()
    expect(screen.getByText('@alice_x')).toBeInTheDocument()
    expect(screen.getByText('My Page')).toBeInTheDocument()
  })

  it('shows character counters for platforms with limits only', () => {
    renderDialog({ accounts: [blueskyAccount, xAccount, facebookAccount] })
    // Bluesky (300) and X (280) should show counters
    expect(screen.getByText(/\/300/)).toBeInTheDocument()
    expect(screen.getByText(/\/280/)).toBeInTheDocument()
  })
})
