import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import type { CrossPostResult } from '@/api/crosspost'
import CrossPostHistory from '../CrossPostHistory'

const postedItem: CrossPostResult = {
  id: 1,
  post_path: 'posts/2026-02-20-hello/index.md',
  platform: 'bluesky',
  platform_id: 'at://did:plc:abc/app.bsky.feed.post/123',
  status: 'posted',
  posted_at: '2026-02-20T14:30:00Z',
  error: null,
}

const failedItem: CrossPostResult = {
  id: 2,
  post_path: 'posts/2026-02-20-hello/index.md',
  platform: 'mastodon',
  platform_id: null,
  status: 'failed',
  posted_at: null,
  error: 'Rate limited',
}

describe('CrossPostHistory', () => {
  it('shows loading text when loading is true', () => {
    render(<CrossPostHistory items={[]} loading={true} />)
    expect(screen.getByText('Loading cross-post history...')).toBeInTheDocument()
  })

  it('shows "No cross-posts yet." when items is empty and not loading', () => {
    render(<CrossPostHistory items={[]} loading={false} />)
    expect(screen.getByText('No cross-posts yet.')).toBeInTheDocument()
  })

  it('renders history items with platform name and status', () => {
    render(<CrossPostHistory items={[postedItem, failedItem]} loading={false} />)

    expect(screen.getByText('Bluesky')).toBeInTheDocument()
    expect(screen.getByText('Mastodon')).toBeInTheDocument()
    expect(screen.getByText('Posted')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('shows error message for failed items', () => {
    render(<CrossPostHistory items={[failedItem]} loading={false} />)

    expect(screen.getByText('Rate limited')).toBeInTheDocument()
  })

  it('shows formatted timestamp for posted items', () => {
    render(<CrossPostHistory items={[postedItem]} loading={false} />)

    const expectedDate = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-02-20T14:30:00Z'))
    expect(screen.getByText(expectedDate)).toBeInTheDocument()
  })

  it('does not show error message for successful items', () => {
    render(<CrossPostHistory items={[postedItem]} loading={false} />)

    expect(screen.queryByText('Rate limited')).not.toBeInTheDocument()
  })
})
