import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet, mockPost, mockPut } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: mockGet, post: mockPost, put: mockPut },
}))

import {
  fetchBroadcasts,
  fetchSubscriptionSettings,
  sendTestEmail,
  subscribe,
  triggerBroadcast,
  updateSubscriptionSettings,
} from '@/api/subscriptions'

function mockJsonResponse(payload: unknown) {
  return { json: vi.fn().mockResolvedValue(payload) }
}

describe('subscribe', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('posts the email to subscribe', async () => {
    mockPost.mockReturnValue(mockJsonResponse({ message: 'ok' }))

    const res = await subscribe('r@x.com')

    expect(mockPost).toHaveBeenCalledWith('subscribe', { json: { email: 'r@x.com' } })
    expect(res.message).toBe('ok')
  })
})

describe('sendTestEmail', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('posts the email to admin/subscriptions/test', async () => {
    mockPost.mockReturnValue(mockJsonResponse({ message: 'sent' }))

    const res = await sendTestEmail('a@b.com')

    expect(mockPost).toHaveBeenCalledWith('admin/subscriptions/test', {
      json: { email: 'a@b.com' },
    })
    expect(res.message).toBe('sent')
  })
})

describe('fetchSubscriptionSettings', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('calls GET admin/subscriptions/settings', async () => {
    const settings = {
      enabled: true,
      from_email: 'noreply@example.com',
      from_name: null,
      controller_name: null,
      controller_contact: null,
      privacy_policy_url: null,
      postal_address: null,
      key_configured: true,
      webhook_secret_configured: true,
      segment_configured: false,
      subscriber_count: 42,
    }
    mockGet.mockReturnValue(mockJsonResponse(settings))

    const res = await fetchSubscriptionSettings()

    const [url] = mockGet.mock.calls[0] as [string]
    expect(url).toBe('admin/subscriptions/settings')
    expect(res.enabled).toBe(true)
    expect(res.subscriber_count).toBe(42)
  })
})

describe('updateSubscriptionSettings', () => {
  beforeEach(() => {
    mockPut.mockReset()
  })

  it('calls PUT admin/subscriptions/settings with patch', async () => {
    const updated = {
      enabled: false,
      from_email: null,
      from_name: null,
      controller_name: null,
      controller_contact: null,
      privacy_policy_url: null,
      postal_address: null,
      key_configured: false,
      webhook_secret_configured: false,
      segment_configured: false,
      subscriber_count: null,
    }
    mockPut.mockReturnValue(mockJsonResponse(updated))

    const res = await updateSubscriptionSettings({ enabled: false })

    const [url, options] = mockPut.mock.calls[0] as [string, { json: { enabled: boolean } }]
    expect(url).toBe('admin/subscriptions/settings')
    expect(options.json).toEqual({ enabled: false })
    expect(res.enabled).toBe(false)
  })
})

describe('triggerBroadcast', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('posts to admin/subscriptions/broadcasts with post_path', async () => {
    mockPost.mockReturnValue(mockJsonResponse({ message: 'queued' }))

    const res = await triggerBroadcast('posts/x/index.md')

    expect(mockPost).toHaveBeenCalledWith('admin/subscriptions/broadcasts', {
      json: { post_path: 'posts/x/index.md' },
    })
    expect(res.message).toBe('queued')
  })
})

describe('fetchBroadcasts', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('calls GET admin/subscriptions/broadcasts', async () => {
    const payload = {
      broadcasts: [
        {
          id: 1,
          post_path: 'posts/x/index.md',
          post_title: 'Hello',
          resend_broadcast_id: null,
          trigger: 'manual',
          status: 'sent',
          sent_at: '2026-01-01T00:00:00Z',
          error: null,
        },
      ],
    }
    mockGet.mockReturnValue(mockJsonResponse(payload))

    const res = await fetchBroadcasts()

    const [url] = mockGet.mock.calls[0] as [string]
    expect(url).toBe('admin/subscriptions/broadcasts')
    expect(res.broadcasts).toHaveLength(1)
    const first = res.broadcasts[0]
    expect(first?.post_title).toBe('Hello')
  })
})
