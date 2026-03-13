import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import ShareBar from '../ShareBar'
import * as shareUtils from '../shareUtils'

import { storage } from './testUtils'

describe('ShareBar', () => {
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

  it('renders share, email, and copy link buttons directly', () => {
    render(<ShareBar {...defaultProps} />)
    expect(screen.getByLabelText('Share this post')).toBeInTheDocument()
    expect(screen.getByLabelText('Share via email')).toBeInTheDocument()
    expect(screen.getByLabelText('Copy link')).toBeInTheDocument()
  })

  it('disables all share actions when the post is a draft', async () => {
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} disabled={true} />)

    const shareButton = screen.getByLabelText('Share this post')
    const emailButton = screen.getByLabelText('Share via email')
    const copyButton = screen.getByLabelText('Copy link')

    expect(shareButton).toBeDisabled()
    expect(emailButton).toBeDisabled()
    expect(copyButton).toBeDisabled()

    await user.click(shareButton)

    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
    expect(screen.getByText('Publish this draft to enable sharing.')).toBeInTheDocument()
  })

  it('does not show platform buttons directly', () => {
    render(<ShareBar {...defaultProps} />)
    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Share on X')).not.toBeInTheDocument()
  })

  it('opens dropdown with all platforms when share button is clicked', async () => {
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))

    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Facebook')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Hacker News')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on LinkedIn')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Mastodon')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Reddit')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on X')).toBeInTheDocument()
  })

  it('opens share URL in new tab from dropdown', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Bluesky'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://bsky.app/intent/compose?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('shows mastodon instance prompt from dropdown when no saved instance', async () => {
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
  })

  it('shares to mastodon directly from dropdown when instance is saved', async () => {
    storage.set('agblogger:mastodon-instance', 'hachyderm.io')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://hachyderm.io/share?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('shows mastodon prompt from dropdown when saved instance is invalid', async () => {
    storage.set('agblogger:mastodon-instance', 'evil.com/phishing')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share this post'))
    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).not.toHaveBeenCalled()
    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
    windowOpen.mockRestore()
  })

  it('copies link and shows feedback on direct copy button click', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    })
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Copy link'))

    await waitFor(() => {
      expect(screen.getByText('Copied!')).toBeInTheDocument()
    })
  })

  it('shows failure feedback when copy fails', async () => {
    vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(false)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Copy link'))

    await waitFor(() => {
      expect(screen.getByText('Copy failed')).toBeInTheDocument()
    })
  })

  it('opens email share link with mailto from direct button', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share via email'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('mailto:?subject='),
      '_self',
    )
    windowOpen.mockRestore()
  })

  it('closes dropdown when clicking outside', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <ShareBar {...defaultProps} />
        <span>outside</span>
      </div>,
    )

    await user.click(screen.getByLabelText('Share this post'))
    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()

    await user.click(screen.getByText('outside'))
    expect(screen.queryByLabelText('Share on Bluesky')).not.toBeInTheDocument()
  })
})
