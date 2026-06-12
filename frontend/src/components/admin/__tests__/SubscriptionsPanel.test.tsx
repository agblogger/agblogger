import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/subscriptions')
vi.mock('@/api/posts')
vi.mock('@/stores/siteStore', () => ({ refreshSiteConfig: vi.fn() }))
vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: {},
    HTTPError: MockHTTPError,
  }
})

import * as apiMod from '@/api/subscriptions'
import * as postsMod from '@/api/posts'
import SubscriptionsPanel from '@/components/admin/SubscriptionsPanel'
import { refreshSiteConfig } from '@/stores/siteStore'
import { MockHTTPError } from '@/test/MockHTTPError'

const FULL_SETTINGS = {
  enabled: true,
  from_email: 'a@b.com',
  from_name: 'J',
  controller_name: 'J',
  controller_contact: 'j@b.com',
  privacy_policy_url: 'https://b/p',
  postal_address: 'x',
  key_configured: true,
  webhook_secret_configured: true,
  segment_configured: true,
  subscriber_count: 42,
}

const INCOMPLETE_SETTINGS = {
  ...FULL_SETTINGS,
  key_configured: false,
  from_email: null,
  controller_name: null,
  enabled: false,
}

function setupDefaults() {
  vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue(FULL_SETTINGS)
  vi.mocked(apiMod.fetchBroadcasts).mockResolvedValue({ broadcasts: [] })
  vi.mocked(postsMod.fetchPosts).mockResolvedValue({
    posts: [],
    total: 0,
    page: 1,
    per_page: 50,
    total_pages: 0,
  })
}

function mockPostsWithOnePublished() {
  vi.mocked(postsMod.fetchPosts).mockResolvedValue({
    posts: [
      {
        id: 1,
        file_path: 'posts/hello',
        title: 'Hello World',
        subtitle: null,
        author: null,
        created_at: '2024-01-01T00:00:00Z',
        modified_at: '2024-01-01T00:00:00Z',
        is_draft: false,
        rendered_excerpt: null,
        labels: [],
        word_count: 0,
      },
    ],
    total: 1,
    page: 1,
    per_page: 50,
    total_pages: 1,
  })
}

function renderPanel(props: { busy?: boolean; onBusyChange?: (b: boolean) => void } = {}) {
  const defaultProps = { busy: false, onBusyChange: vi.fn(), ...props }
  return render(<SubscriptionsPanel {...defaultProps} />)
}

describe('SubscriptionsPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setupDefaults()
  })

  it('shows subscriber count and API key status', async () => {
    renderPanel()
    expect(await screen.findByText(/42/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText(/configured/i)).toHaveLength(1))
    expect(screen.queryByLabelText(/webhook signing secret/i)).not.toBeInTheDocument()
  })

  it('shows loading state initially, then content', async () => {
    let resolve!: (v: typeof FULL_SETTINGS) => void
    vi.mocked(apiMod.fetchSubscriptionSettings).mockReturnValue(
      new Promise<typeof FULL_SETTINGS>((r) => { resolve = r }),
    )
    renderPanel()
    expect(screen.getByRole('status')).toBeInTheDocument()
    resolve(FULL_SETTINGS)
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('shows the required user-provided settings when enable is not allowed', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue(INCOMPLETE_SETTINGS)
    renderPanel()
    await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(screen.getByText(/requires api key \+ from email/i)).toBeInTheDocument()
  })

  it('enable toggle is DISABLED when api key or from_email is missing', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue(INCOMPLETE_SETTINGS)
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeDisabled()
  })

  it('enable toggle is ENABLED when webhook secret has not been provisioned yet', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue({
      ...FULL_SETTINGS,
      enabled: false,
      webhook_secret_configured: false,
    })
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeEnabled()
  })

  it('explains missing webhook setup and retry timing', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue({
      ...FULL_SETTINGS,
      webhook_secret_configured: false,
    })
    renderPanel()
    expect(
      await screen.findByText(/webhook unavailable.*other features work/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/unsubscribed contacts will remain in resend/i)).toBeInTheDocument()
    expect(screen.getByText(/requires public https.*retries.*settings.*saved/i)).toBeInTheDocument()
  })

  it('enable toggle is ENABLED when key and from_email are configured, even without compliance fields', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue({
      ...FULL_SETTINGS,
      controller_name: null,
      controller_contact: null,
      privacy_policy_url: null,
      postal_address: null,
    })
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeEnabled()
  })

  it('enable toggle is ENABLED when all compliance fields and key are configured', async () => {
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeEnabled()
  })

  it('toggle calls updateSubscriptionSettings with enabled', async () => {
    const user = userEvent.setup()
    vi.mocked(apiMod.updateSubscriptionSettings).mockResolvedValue({
      ...FULL_SETTINGS,
      enabled: false,
    })
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    await user.click(toggle)
    await waitFor(() =>
      expect(apiMod.updateSubscriptionSettings).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: false }),
      ),
    )
    expect(refreshSiteConfig).toHaveBeenCalled()
  })

  it('save calls updateSubscriptionSettings without api_key when input is empty', async () => {
    const user = userEvent.setup()
    vi.mocked(apiMod.updateSubscriptionSettings).mockResolvedValue(FULL_SETTINGS)
    renderPanel()
    await screen.findByText(/42/)
    const saveBtn = screen.getByRole('button', { name: /save settings/i })
    await user.click(saveBtn)
    await waitFor(() =>
      expect(apiMod.updateSubscriptionSettings).toHaveBeenCalledWith(
        expect.not.objectContaining({ api_key: expect.anything() as string }),
      ),
    )
  })

  it('save includes api_key when input is filled', async () => {
    const user = userEvent.setup()
    vi.mocked(apiMod.updateSubscriptionSettings).mockResolvedValue({
      ...FULL_SETTINGS,
      key_configured: true,
    })
    renderPanel()
    await screen.findByText(/42/)
    const keyInput = screen.getByLabelText(/resend api key/i)
    await user.type(keyInput, 'test-api-key')
    const saveBtn = screen.getByRole('button', { name: /save settings/i })
    await user.click(saveBtn)
    await waitFor(() =>
      expect(apiMod.updateSubscriptionSettings).toHaveBeenCalledWith(
        expect.objectContaining({ api_key: 'test-api-key' }),
      ),
    )
  })

  it('api_key input is cleared after successful save', async () => {
    const user = userEvent.setup()
    vi.mocked(apiMod.updateSubscriptionSettings).mockResolvedValue(FULL_SETTINGS)
    renderPanel()
    await screen.findByText(/42/)
    const keyInput = screen.getByLabelText(/resend api key/i)
    await user.type(keyInput, 'test-key')
    await user.click(screen.getByRole('button', { name: /save settings/i }))
    await waitFor(() => expect(keyInput).toHaveValue(''))
  })

  it('shows 400 detail error from updateSubscriptionSettings', async () => {
    vi.mocked(apiMod.updateSubscriptionSettings).mockRejectedValue(
      new MockHTTPError(400, JSON.stringify({ detail: 'Enable precondition not met.' })),
    )
    const user = userEvent.setup()
    renderPanel()
    await screen.findByText(/42/)
    await user.click(screen.getByRole('button', { name: /save settings/i }))
    await waitFor(() =>
      expect(screen.getByText(/enable precondition not met/i)).toBeInTheDocument(),
    )
  })

  it('requests posts with a backend-valid per_page (<= 100)', async () => {
    renderPanel()
    await screen.findByText(/42/)
    expect(vi.mocked(postsMod.fetchPosts)).toHaveBeenCalledWith(
      expect.objectContaining({ per_page: 100 }),
    )
    const callArg = vi.mocked(postsMod.fetchPosts).mock.calls[0]?.[0]
    expect(callArg?.per_page).toBeLessThanOrEqual(100)
  })

  it('loads published posts from every posts page', async () => {
    vi.mocked(postsMod.fetchPosts)
      .mockResolvedValueOnce({
        posts: [],
        total: 101,
        page: 1,
        per_page: 100,
        total_pages: 2,
      })
      .mockResolvedValueOnce({
        posts: [
          {
            id: 101,
            file_path: 'posts/older',
            title: 'Older Published Post',
            subtitle: null,
            author: null,
            created_at: '2023-01-01T00:00:00Z',
            modified_at: '2023-01-01T00:00:00Z',
            is_draft: false,
            rendered_excerpt: null,
            labels: [],
            word_count: 0,
          },
        ],
        total: 101,
        page: 2,
        per_page: 100,
        total_pages: 2,
      })

    renderPanel()

    expect(await screen.findByRole('option', { name: 'Older Published Post' })).toBeInTheDocument()
    expect(postsMod.fetchPosts).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ page: 2, per_page: 100 }),
    )
  })

  it('shows error banner (not success) when the polled ledger row has status=failed', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(apiMod.triggerBroadcast).mockResolvedValue({ message: 'Broadcast started' })
    vi.mocked(apiMod.fetchBroadcasts)
      .mockResolvedValueOnce({ broadcasts: [] })
      .mockResolvedValue({
        broadcasts: [{
          id: 99,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: null,
          trigger: 'manual' as const,
          status: 'failed' as const,
          sent_at: '2024-01-01T12:00:00Z',
          error: 'Resend API unavailable',
        }],
      })
    mockPostsWithOnePublished()
    renderPanel()
    await screen.findByText(/42/)
    await user.selectOptions(screen.getByRole('combobox', { name: /select post/i }), 'posts/hello')
    await user.click(screen.getByRole('button', { name: /send broadcast/i }))

    // Error banner should contain the error text (may also appear in table)
    await waitFor(() => {
      const allMatches = screen.getAllByText(/resend api unavailable/i)
      const errorBanner = allMatches.find((el) => el.className.includes('red'))
      expect(errorBanner).toBeInTheDocument()
    })
    // No success banner should remain
    expect(screen.queryByText(/broadcast started/i)).not.toBeInTheDocument()
  })

  it('send broadcast calls triggerBroadcast after confirm', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(apiMod.triggerBroadcast).mockResolvedValue({ message: 'ok' })
    mockPostsWithOnePublished()
    renderPanel()
    await screen.findByText(/42/)
    const select = await screen.findByRole('combobox', { name: /select post/i })
    await user.selectOptions(select, 'posts/hello')
    const broadcastBtn = screen.getByRole('button', { name: /send broadcast/i })
    await user.click(broadcastBtn)
    await waitFor(() =>
      expect(apiMod.triggerBroadcast).toHaveBeenCalledWith('posts/hello'),
    )
  })

  it('polls until the triggered broadcast appears in history', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(apiMod.triggerBroadcast).mockResolvedValue({ message: 'Broadcast started' })
    let fetchCount = 0
    vi.mocked(apiMod.fetchBroadcasts).mockImplementation(async () => {
      fetchCount += 1
      return fetchCount < 3 ? { broadcasts: [] } : {
        broadcasts: [{
          id: 7,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: null,
          trigger: 'manual',
          status: 'failed',
          sent_at: '2024-01-01T12:00:00Z',
          error: 'Delivery failed',
        }],
      }
    })
    mockPostsWithOnePublished()
    renderPanel()
    await screen.findByText(/42/)
    await user.selectOptions(screen.getByRole('combobox', { name: /select post/i }), 'posts/hello')
    await user.click(screen.getByRole('button', { name: /send broadcast/i }))

    const matches = await screen.findAllByText('Delivery failed', {}, { timeout: 3000 })
    expect(matches.length).toBeGreaterThanOrEqual(1)
    expect(fetchCount).toBeGreaterThanOrEqual(3)
  })

  it('shows completed status only after the ledger reports sent', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(apiMod.triggerBroadcast).mockResolvedValue({ message: 'Broadcast queued' })
    vi.mocked(apiMod.fetchBroadcasts)
      .mockResolvedValueOnce({ broadcasts: [] })
      .mockResolvedValueOnce({
        broadcasts: [{
          id: 7,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: 'br_7',
          trigger: 'manual',
          status: 'sent',
          sent_at: '2024-01-01T12:00:00Z',
          error: null,
        }],
      })
    mockPostsWithOnePublished()
    renderPanel()
    await screen.findByText(/42/)
    await user.selectOptions(screen.getByRole('combobox', { name: /select post/i }), 'posts/hello')
    await user.click(screen.getByRole('button', { name: /send broadcast/i }))

    expect(await screen.findByText('Broadcast sent.')).toBeInTheDocument()
    expect(screen.queryByText(/broadcast queued|broadcast started/i)).not.toBeInTheDocument()
  })

  it('does NOT call triggerBroadcast when confirm is cancelled', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    vi.mocked(apiMod.triggerBroadcast).mockResolvedValue({ message: 'ok' })
    mockPostsWithOnePublished()
    renderPanel()
    await screen.findByText(/42/)
    const select = await screen.findByRole('combobox', { name: /select post/i })
    await user.selectOptions(select, 'posts/hello')
    await user.click(screen.getByRole('button', { name: /send broadcast/i }))
    expect(apiMod.triggerBroadcast).not.toHaveBeenCalled()
  })

  it('renders broadcast history rows from fetchBroadcasts', async () => {
    vi.mocked(apiMod.fetchBroadcasts).mockResolvedValue({
      broadcasts: [
        {
          id: 1,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: 'br_123',
          trigger: 'manual',
          status: 'sent',
          sent_at: '2024-01-01T12:00:00Z',
          error: null,
        },
      ],
    })
    renderPanel()
    await screen.findByText(/42/)
    await waitFor(() => expect(screen.getByText('Hello World')).toBeInTheDocument())
    expect(screen.getByText('sent')).toBeInTheDocument()
  })

  it('renders failed broadcast row with error styling', async () => {
    vi.mocked(apiMod.fetchBroadcasts).mockResolvedValue({
      broadcasts: [
        {
          id: 2,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: 'br_456',
          trigger: 'manual',
          status: 'failed',
          sent_at: '2024-01-02T12:00:00Z',
          error: 'Segment not found',
        },
      ],
    })
    renderPanel()
    await screen.findByText(/42/)
    await waitFor(() => expect(screen.getByText('Hello World')).toBeInTheDocument())
    const statusBadge = screen.getByText('failed')
    expect(statusBadge).toBeInTheDocument()
    expect(statusBadge.className).toMatch(/red/)
    expect(screen.getByText('Segment not found')).toBeInTheDocument()
  })

  it('renders the broadcast sent-at timestamp as a localized string', async () => {
    vi.mocked(apiMod.fetchBroadcasts).mockResolvedValue({
      broadcasts: [
        {
          id: 5,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: 'br_5',
          trigger: 'manual',
          status: 'sent',
          sent_at: '2024-01-01T12:00:00Z',
          error: null,
        },
      ],
    })
    renderPanel()
    await screen.findByText(/42/)
    const expected = new Date('2024-01-01T12:00:00Z').toLocaleString()
    await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
  })

  it('shows empty state when no broadcasts', async () => {
    renderPanel()
    await screen.findByText(/42/)
    await waitFor(() =>
      expect(screen.getByText(/no broadcasts yet/i)).toBeInTheDocument(),
    )
  })

  it('calls sendTestEmail from test-email control', async () => {
    const user = userEvent.setup()
    vi.mocked(apiMod.sendTestEmail).mockResolvedValue({ message: 'Test email sent.' })
    renderPanel()
    await screen.findByText(/42/)
    const emailInput = screen.getByRole('textbox', { name: /test email address/i })
    await user.clear(emailInput)
    await user.type(emailInput, 'test@example.com')
    await user.click(screen.getByRole('button', { name: /send test email/i }))
    await waitFor(() =>
      expect(apiMod.sendTestEmail).toHaveBeenCalledWith('test@example.com'),
    )
  })

  it('calls onBusyChange(true/false) around save', async () => {
    let resolveUpdate!: (v: typeof FULL_SETTINGS) => void
    vi.mocked(apiMod.updateSubscriptionSettings).mockReturnValue(
      new Promise<typeof FULL_SETTINGS>((r) => { resolveUpdate = r }),
    )
    const onBusyChange = vi.fn()
    const user = userEvent.setup()
    renderPanel({ onBusyChange })
    await screen.findByText(/42/)
    await user.click(screen.getByRole('button', { name: /save settings/i }))
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(true))
    resolveUpdate(FULL_SETTINGS)
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(false))
  })

  it('disables all controls while busy={true}', async () => {
    renderPanel({ busy: true })
    await screen.findByText(/42/)
    const toggle = screen.getByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeDisabled()
    expect(screen.getByRole('button', { name: /save settings/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /send test email/i })).toBeDisabled()
  })

  it('calls onBusyChange(true/false) around the enable toggle', async () => {
    let resolveUpdate!: (v: typeof FULL_SETTINGS) => void
    vi.mocked(apiMod.updateSubscriptionSettings).mockReturnValue(
      new Promise<typeof FULL_SETTINGS>((r) => { resolveUpdate = r }),
    )
    const onBusyChange = vi.fn()
    const user = userEvent.setup()
    renderPanel({ onBusyChange })
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    await user.click(toggle)
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(true))
    resolveUpdate({ ...FULL_SETTINGS, enabled: false })
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(false))
  })

  it('calls onBusyChange(true/false) around a confirmed broadcast', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockPostsWithOnePublished()
    let resolveTrigger!: (v: { message: string }) => void
    vi.mocked(apiMod.triggerBroadcast).mockReturnValue(
      new Promise<{ message: string }>((r) => { resolveTrigger = r }),
    )
    vi.mocked(apiMod.fetchBroadcasts)
      .mockResolvedValueOnce({ broadcasts: [] })
      .mockResolvedValueOnce({
        broadcasts: [{
          id: 8,
          post_path: 'posts/hello',
          post_title: 'Hello World',
          resend_broadcast_id: 'br_8',
          trigger: 'manual',
          status: 'sent',
          sent_at: '2024-01-01T12:00:00Z',
          error: null,
        }],
      })
    const onBusyChange = vi.fn()
    const user = userEvent.setup()
    renderPanel({ onBusyChange })
    await screen.findByText(/42/)
    const select = await screen.findByRole('combobox', { name: /select post/i })
    await user.selectOptions(select, 'posts/hello')
    await user.click(screen.getByRole('button', { name: /send broadcast/i }))
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(true))
    resolveTrigger({ message: 'ok' })
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(false))
  })

  it('calls onBusyChange(true/false) around a test email', async () => {
    let resolveTest!: (v: { message: string }) => void
    vi.mocked(apiMod.sendTestEmail).mockReturnValue(
      new Promise<{ message: string }>((r) => { resolveTest = r }),
    )
    const onBusyChange = vi.fn()
    const user = userEvent.setup()
    renderPanel({ onBusyChange })
    await screen.findByText(/42/)
    const emailInput = screen.getByRole('textbox', { name: /test email address/i })
    await user.type(emailInput, 'test@example.com')
    await user.click(screen.getByRole('button', { name: /send test email/i }))
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(true))
    resolveTest({ message: 'sent' })
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(false))
  })

  it('shows an error banner when the mount load fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(apiMod.fetchSubscriptionSettings).mockRejectedValue(new Error('network'))
    renderPanel()
    await waitFor(() =>
      expect(screen.getByText(/failed to load subscription settings/i)).toBeInTheDocument(),
    )
  })

  it('shows session expired on a 401 save', async () => {
    vi.mocked(apiMod.updateSubscriptionSettings).mockRejectedValue(new MockHTTPError(401))
    const user = userEvent.setup()
    renderPanel()
    await screen.findByText(/42/)
    await user.click(screen.getByRole('button', { name: /save settings/i }))
    await waitFor(() =>
      expect(screen.getByText(/session expired/i)).toBeInTheDocument(),
    )
  })
})
