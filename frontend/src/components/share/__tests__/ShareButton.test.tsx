import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import ShareButton from '../ShareButton'
import * as shareUtils from '../shareUtils'

import { storage } from './testUtils'

describe('ShareButton', () => {
  const defaultProps = {
    title: 'Hello World',
    author: 'Alice' as string | null,
    url: 'https://blog.example.com/post/hello',
  }

  beforeEach(() => {
    storage.clear()
    vi.resetAllMocks()
  })

  afterEach(() => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
  })

  it('renders a share button', () => {
    render(<ShareButton {...defaultProps} />)
    expect(screen.getByLabelText('Share this post')).toBeInTheDocument()
  })

  it('always opens dropdown on click, showing all platform options', async () => {
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))

    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Mastodon')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on X')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Facebook')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on LinkedIn')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Reddit')).toBeInTheDocument()
    expect(screen.getByLabelText('Share via email')).toBeInTheDocument()
    expect(screen.getByLabelText('Copy link')).toBeInTheDocument()
  })

  it('shows native share option in dropdown when available', async () => {
    Object.defineProperty(navigator, 'share', {
      value: vi.fn().mockResolvedValue(undefined),
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))

    expect(screen.getByLabelText('Share via device')).toBeInTheDocument()
  })

  it('hides native share option when unavailable', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))

    expect(screen.queryByLabelText('Share via device')).not.toBeInTheDocument()
  })

  it('calls navigator.share when clicking native share option in dropdown', async () => {
    const mockShare = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'share', {
      value: mockShare,
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share via device'))

    expect(mockShare).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Hello World',
        url: 'https://blog.example.com/post/hello',
      }),
    )
  })

  it('closes dropdown when clicking outside', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(
      <div>
        <ShareButton {...defaultProps} />
        <span>outside</span>
      </div>,
    )

    await user.click(screen.getByLabelText('Share this post'))
    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()

    await user.click(screen.getByText('outside'))
    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
  })

  it('opens platform share URL from dropdown', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Bluesky'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://bsky.app/intent/compose?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('closes dropdown after clicking a platform', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on X'))

    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
  })

  it('shows mastodon prompt when no saved instance', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
  })

  it('shares to mastodon directly when instance is saved', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    storage.set('agblogger:mastodon-instance', 'hachyderm.io')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://hachyderm.io/share?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('shows mastodon prompt when saved instance is invalid', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    storage.set('agblogger:mastodon-instance', 'evil.com/phishing')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).not.toHaveBeenCalled()
    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
    windowOpen.mockRestore()
  })

  it('toggles dropdown open and closed', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Share this post'))
    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
  })

  // Issue #13: email share from dropdown
  it('opens email share link from dropdown', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share via email'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('mailto:?subject='),
      '_self',
    )
    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
    windowOpen.mockRestore()
  })

  // Issue #13: copy link from dropdown shows feedback
  it('copies link and shows copied feedback in dropdown', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Copy link'))

    await waitFor(() => {
      expect(screen.getByText('Copied!')).toBeInTheDocument()
    })
  })

  // Issue #3: copy failure should show feedback
  it('shows failure feedback when copy fails in dropdown', async () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(false)
    const user = userEvent.setup()
    render(<ShareButton {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Copy link'))

    await waitFor(() => {
      expect(screen.getByText('Copy failed')).toBeInTheDocument()
    })
  })
})
