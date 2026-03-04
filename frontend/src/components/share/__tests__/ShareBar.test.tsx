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

  it('renders all platform share buttons', () => {
    render(<ShareBar {...defaultProps} />)
    expect(screen.getByLabelText('Share on Bluesky')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Mastodon')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on X')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Facebook')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on LinkedIn')).toBeInTheDocument()
    expect(screen.getByLabelText('Share on Reddit')).toBeInTheDocument()
    expect(screen.getByLabelText('Share via email')).toBeInTheDocument()
    expect(screen.getByLabelText('Copy link')).toBeInTheDocument()
  })

  it('opens share URL in new tab when platform button is clicked', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share on Bluesky'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://bsky.app/intent/compose?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('shows mastodon instance prompt when mastodon button clicked and no saved instance', async () => {
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
  })

  it('shares to mastodon directly when instance is saved in localStorage', async () => {
    storage.set('agblogger:mastodon-instance', 'hachyderm.io')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).toHaveBeenCalledWith(
      expect.stringContaining('https://hachyderm.io/share?text='),
      '_blank',
      'noopener,noreferrer',
    )
    windowOpen.mockRestore()
  })

  it('shows mastodon prompt when saved instance in localStorage is invalid', async () => {
    storage.set('agblogger:mastodon-instance', 'evil.com/phishing')
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share on Mastodon'))

    expect(windowOpen).not.toHaveBeenCalled()
    expect(screen.getByPlaceholderText('mastodon.social')).toBeInTheDocument()
    windowOpen.mockRestore()
  })

  it('copies link and shows feedback on copy button click', async () => {
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

  // Issue #3: copy failure should show feedback
  it('shows failure feedback when copy fails', async () => {
    vi.spyOn(shareUtils, 'copyToClipboard').mockResolvedValue(false)
    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Copy link'))

    await waitFor(() => {
      expect(screen.getByText('Copy failed')).toBeInTheDocument()
    })
  })

  it('shows native share button when navigator.share is available', () => {
    Object.defineProperty(navigator, 'share', {
      value: vi.fn(),
      writable: true,
      configurable: true,
    })
    render(<ShareBar {...defaultProps} />)
    expect(screen.getByLabelText('Share via device')).toBeInTheDocument()
  })

  it('hides native share button when navigator.share is unavailable', () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    render(<ShareBar {...defaultProps} />)
    expect(screen.queryByLabelText('Share via device')).not.toBeInTheDocument()
  })

  // Issue #2: unhandled rejection from native share non-AbortError
  it('does not fire unhandledrejection when native share rejects with non-AbortError', async () => {
    const typeError = new TypeError('Invalid share data')
    Object.defineProperty(navigator, 'share', {
      value: vi.fn().mockRejectedValue(typeError),
      writable: true,
      configurable: true,
    })

    const unhandledHandler = vi.fn()
    window.addEventListener('unhandledrejection', unhandledHandler)

    const user = userEvent.setup()
    render(<ShareBar {...defaultProps} />)

    await user.click(screen.getByLabelText('Share via device'))

    // Give the microtask queue time to settle
    await new Promise((r) => setTimeout(r, 50))

    expect(unhandledHandler).not.toHaveBeenCalled()
    window.removeEventListener('unhandledrejection', unhandledHandler)
  })

  // Issue #13: email share button
  it('opens email share link with mailto', async () => {
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
})
