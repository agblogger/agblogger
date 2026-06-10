import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/subscriptions')
vi.mock('@/api/posts')
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

  it('shows subscriber count and key status', async () => {
    renderPanel()
    expect(await screen.findByText(/42/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/configured/i)).toBeInTheDocument())
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

  it('enable toggle is DISABLED when compliance fields are missing', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue(INCOMPLETE_SETTINGS)
    renderPanel()
    const toggle = await screen.findByRole('switch', { name: /enable subscriptions/i })
    expect(toggle).toBeDisabled()
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
    const keyInput = screen.getByPlaceholderText(/configured|not set/i)
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
    const keyInput = screen.getByPlaceholderText(/configured|not set/i)
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
