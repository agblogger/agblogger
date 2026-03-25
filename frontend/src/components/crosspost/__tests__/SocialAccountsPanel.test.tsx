import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SWRConfig } from 'swr'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { MockHTTPError } from '@/test/MockHTTPError'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { HTTPError: MockHTTPError }
})

import SocialAccountsPanel from '../SocialAccountsPanel'

const mockFetchSocialAccounts = vi.fn()
const mockDeleteSocialAccount = vi.fn()
const mockAuthorizeBluesky = vi.fn()
const mockAuthorizeMastodon = vi.fn()
const mockAuthorizeX = vi.fn()
const mockAuthorizeFacebook = vi.fn()
const mockSelectFacebookPage = vi.fn()
const mockFetchFacebookPages = vi.fn()

vi.mock('@/api/crosspost', () => ({
  fetchSocialAccounts: (...args: unknown[]) => mockFetchSocialAccounts(...args) as unknown,
  deleteSocialAccount: (...args: unknown[]) => mockDeleteSocialAccount(...args) as unknown,
  authorizeBluesky: (...args: unknown[]) => mockAuthorizeBluesky(...args) as unknown,
  authorizeMastodon: (...args: unknown[]) => mockAuthorizeMastodon(...args) as unknown,
  authorizeX: (...args: unknown[]) => mockAuthorizeX(...args) as unknown,
  authorizeFacebook: (...args: unknown[]) => mockAuthorizeFacebook(...args) as unknown,
  selectFacebookPage: (...args: unknown[]) => mockSelectFacebookPage(...args) as unknown,
  fetchFacebookPages: (...args: unknown[]) => mockFetchFacebookPages(...args) as unknown,
}))

function renderPanel(props: { busy?: boolean; onBusyChange?: (busy: boolean) => void } = {}) {
  const defaultProps = {
    busy: false,
    onBusyChange: vi.fn(),
    ...props,
  }
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <SocialAccountsPanel {...defaultProps} />
    </SWRConfig>,
  )
}

describe('SocialAccountsPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchSocialAccounts.mockResolvedValue([])
  })

  it('renders section title "Social Accounts"', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Social Accounts')).toBeInTheDocument()
    })
  })

  it('shows loading spinner initially', () => {
    mockFetchSocialAccounts.mockReturnValue(new Promise(() => {}))
    renderPanel()
    // The spinner is an svg with animate-spin class inside the section
    expect(screen.queryByText('Connect Bluesky')).not.toBeInTheDocument()
  })

  it('shows connect buttons when no accounts exist', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })
    expect(screen.getByText('Connect Mastodon')).toBeInTheDocument()
    expect(screen.getByText('Connect X')).toBeInTheDocument()
    expect(screen.getByText('Connect Facebook')).toBeInTheDocument()
  })

  it('orders available connect platforms alphabetically by displayed platform name', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    const connectLabels = screen
      .getAllByRole('button', { name: /Connect / })
      .map((element) => element.textContent.trim())

    expect(connectLabels).toEqual([
      'Connect Bluesky',
      'Connect Facebook',
      'Connect Mastodon',
      'Connect X',
    ])
  })

  it('shows connected accounts with account name and disconnect button', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Disconnect alice.bsky.social')).toBeInTheDocument()
  })

  it('orders connected accounts alphabetically by displayed platform name', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 4,
        platform: 'x',
        account_name: 'Alpha X Account',
        created_at: '2026-01-16T10:00:00Z',
      },
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'Zulu Bluesky Account',
        created_at: '2026-01-15T10:00:00Z',
      },
      {
        id: 2,
        platform: 'facebook',
        account_name: 'Bravo Facebook Account',
        created_at: '2026-01-17T10:00:00Z',
      },
      {
        id: 3,
        platform: 'mastodon',
        account_name: 'Charlie Mastodon Account',
        created_at: '2026-01-18T10:00:00Z',
      },
    ])

    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Zulu Bluesky Account')).toBeInTheDocument()
    })

    const disconnectLabels = screen
      .getAllByRole('button', { name: /Disconnect / })
      .map((element) => element.getAttribute('aria-label'))

    expect(disconnectLabels).toEqual([
      'Disconnect Zulu Bluesky Account',
      'Disconnect Bravo Facebook Account',
      'Disconnect Charlie Mastodon Account',
      'Disconnect Alpha X Account',
    ])
  })

  it('shows handle input when Connect Bluesky is clicked', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Connect Bluesky'))
    expect(screen.getByLabelText('Bluesky Handle')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('alice.bsky.social')).toBeInTheDocument()
  })

  it('shows instance URL input when Connect Mastodon is clicked', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Connect Mastodon')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Connect Mastodon'))
    expect(screen.getByLabelText('Mastodon Instance URL')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('https://mastodon.social')).toBeInTheDocument()
  })

  it('disables controls when busy prop is true', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    renderPanel({ busy: true })
    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Disconnect alice.bsky.social')).toBeDisabled()
    expect(screen.getByText('Connect Bluesky')).toBeDisabled()
    expect(screen.getByText('Connect Mastodon')).toBeDisabled()
    expect(screen.getByText('Connect X')).toBeDisabled()
    expect(screen.getByText('Connect Facebook')).toBeDisabled()
  })

  it('shows inline disconnect confirmation when trash icon is clicked', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })
    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    expect(screen.getByText('Confirm disconnect?')).toBeInTheDocument()
    expect(screen.getByText('Confirm')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  it('disconnects account on confirm', async () => {
    // Return account on initial load, then empty list on revalidation after delete
    mockFetchSocialAccounts
      .mockResolvedValueOnce([
        {
          id: 1,
          platform: 'bluesky',
          account_name: 'alice.bsky.social',
          created_at: '2026-01-15T10:00:00Z',
        },
      ])
      .mockResolvedValue([])
    mockDeleteSocialAccount.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })
    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    await user.click(screen.getByText('Confirm'))
    await waitFor(() => {
      expect(mockDeleteSocialAccount).toHaveBeenCalledWith(1)
    })
    await waitFor(() => {
      expect(screen.queryByText('alice.bsky.social')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Account disconnected.')).toBeInTheDocument()
  })

  it('shows error when fetching accounts fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockRejectedValue(new Error('Network error'))
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Failed to load social accounts.')).toBeInTheDocument()
    })
  })

  it('does not call onBusyChange again when callback reference changes', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const onBusyChange1 = vi.fn()
    const onBusyChange2 = vi.fn()

    const { rerender } = render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
        <SocialAccountsPanel busy={false} onBusyChange={onBusyChange1} />
      </SWRConfig>,
    )
    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    // Record call count after initial render
    const initialCalls = onBusyChange1.mock.calls.length

    // Re-render with a new callback reference — should NOT trigger extra calls
    rerender(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
        <SocialAccountsPanel busy={false} onBusyChange={onBusyChange2} />
      </SWRConfig>,
    )

    // Wait a tick for effects to settle
    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    // onBusyChange2 should not have been called because localBusy didn't change
    expect(onBusyChange2).not.toHaveBeenCalled()
    // And onBusyChange1 should not have received extra calls beyond initial
    expect(onBusyChange1.mock.calls.length).toBe(initialCalls)
  })

  it('shows redirect message when Connect X is clicked', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Connect X')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Connect X'))
    expect(
      screen.getByText('You will be redirected to X to authorize AgBlogger.'),
    ).toBeInTheDocument()
  })

  it('shows redirect message when Connect Facebook is clicked', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Connect Facebook')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Connect Facebook'))
    expect(
      screen.getByText(
        'You will be redirected to Facebook to authorize AgBlogger and select a Page.',
      ),
    ).toBeInTheDocument()
  })

  it('shows X-connected account with account name', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 3,
        platform: 'x',
        account_name: '@alice_x',
        created_at: '2026-01-17T10:00:00Z',
      },
    ])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('@alice_x')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Disconnect @alice_x')).toBeInTheDocument()
  })

  it('shows Facebook-connected account with account name', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 4,
        platform: 'facebook',
        account_name: 'My Page',
        created_at: '2026-01-18T10:00:00Z',
      },
    ])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('My Page')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Disconnect My Page')).toBeInTheDocument()
  })

  it('shows Bluesky connect form and submits handle', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockResolvedValue([])
    mockAuthorizeBluesky.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Bluesky'))
    await user.type(screen.getByPlaceholderText('alice.bsky.social'), 'test.bsky.social')

    // Click Connect button in the form
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(mockAuthorizeBluesky).toHaveBeenCalledWith('test.bsky.social')
    })
    // Error should be shown since mock rejected
    await waitFor(() => {
      expect(screen.getByText('Failed to start Bluesky authorization. Please try again.')).toBeInTheDocument()
    })
  })

  it('shows Mastodon connect form and submits instance URL', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockResolvedValue([])
    mockAuthorizeMastodon.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Mastodon')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Mastodon'))
    await user.type(screen.getByPlaceholderText('https://mastodon.social'), 'https://infosec.exchange')

    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(mockAuthorizeMastodon).toHaveBeenCalledWith('https://infosec.exchange')
    })
    await waitFor(() => {
      expect(screen.getByText('Failed to start Mastodon authorization. Please try again.')).toBeInTheDocument()
    })
  })

  it('submits X authorization on Connect click', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockResolvedValue([])
    mockAuthorizeX.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect X')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect X'))

    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(mockAuthorizeX).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('Failed to start X authorization. Please try again.')).toBeInTheDocument()
    })
  })

  it('submits Facebook authorization on Connect click', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockResolvedValue([])
    mockAuthorizeFacebook.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Facebook')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Facebook'))

    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(mockAuthorizeFacebook).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('Failed to start Facebook authorization. Please try again.')).toBeInTheDocument()
    })
  })

  it('cancels Bluesky connect form', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Bluesky'))
    expect(screen.getByPlaceholderText('alice.bsky.social')).toBeInTheDocument()

    await user.click(screen.getByText('Cancel'))
    expect(screen.queryByPlaceholderText('alice.bsky.social')).not.toBeInTheDocument()
  })

  it('cancels disconnect confirmation', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    expect(screen.getByText('Confirm disconnect?')).toBeInTheDocument()

    await user.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Confirm disconnect?')).not.toBeInTheDocument()
  })

  it('shows disconnect error', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    mockDeleteSocialAccount.mockRejectedValue(new Error('Network'))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(screen.getByText('Failed to disconnect account. Please try again.')).toBeInTheDocument()
    })
  })

  it('shows connected date for accounts', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText(/Connected/)).toBeInTheDocument()
    })
  })

  it('shows session expired when Facebook pages fetch returns 401', async () => {
    window.history.pushState({}, '', '?fb_pages=test-state')
    mockFetchFacebookPages.mockRejectedValue(new MockHTTPError(401))

    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })

    window.history.pushState({}, '', '/')
  })

  it('shows generic error for 5xx authorization errors instead of parsing response body', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    mockAuthorizeBluesky.mockRejectedValue(
      new MockHTTPError(500, JSON.stringify({ detail: 'Internal: OAuth state corrupt' })),
    )
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Bluesky')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Bluesky'))
    await user.type(screen.getByPlaceholderText('alice.bsky.social'), 'test.bsky.social')
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to start Bluesky authorization. Please try again.'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText(/OAuth state corrupt/)).not.toBeInTheDocument()
  })

  it('shows parsed 4xx error detail when loading accounts fails with client error', async () => {
    mockFetchSocialAccounts.mockRejectedValue(
      new MockHTTPError(403, JSON.stringify({ detail: 'Social accounts feature is disabled' })),
    )
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Social accounts feature is disabled')).toBeInTheDocument()
    })
  })

  it('shows generic fallback when loading accounts fails with 5xx', async () => {
    mockFetchSocialAccounts.mockRejectedValue(
      new MockHTTPError(500, JSON.stringify({ detail: 'Internal: database pool exhausted' })),
    )
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Failed to load social accounts.')).toBeInTheDocument()
    })
    expect(screen.queryByText(/database pool exhausted/)).not.toBeInTheDocument()
  })

  it('shows session expired when loading accounts returns 401', async () => {
    mockFetchSocialAccounts.mockRejectedValue(new MockHTTPError(401))
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('shows parsed 4xx error detail when disconnect fails with client error', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    mockDeleteSocialAccount.mockRejectedValue(
      new MockHTTPError(403, JSON.stringify({ detail: 'Permission denied' })),
    )
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(screen.getByText('Permission denied')).toBeInTheDocument()
    })
  })

  it('shows generic fallback when disconnect fails with 5xx', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    mockDeleteSocialAccount.mockRejectedValue(
      new MockHTTPError(500, JSON.stringify({ detail: 'Internal: connection reset' })),
    )
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(screen.getByText('Failed to disconnect account. Please try again.')).toBeInTheDocument()
    })
    expect(screen.queryByText(/connection reset/)).not.toBeInTheDocument()
  })

  it('shows session expired when disconnect returns 401', async () => {
    mockFetchSocialAccounts.mockResolvedValue([
      {
        id: 1,
        platform: 'bluesky',
        account_name: 'alice.bsky.social',
        created_at: '2026-01-15T10:00:00Z',
      },
    ])
    mockDeleteSocialAccount.mockRejectedValue(new MockHTTPError(401))
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('alice.bsky.social')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Disconnect alice.bsky.social'))
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('cancels Mastodon connect form', async () => {
    mockFetchSocialAccounts.mockResolvedValue([])
    const user = userEvent.setup()
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Connect Mastodon')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Connect Mastodon'))
    expect(screen.getByPlaceholderText('https://mastodon.social')).toBeInTheDocument()

    await user.click(screen.getByText('Cancel'))
    expect(screen.queryByPlaceholderText('https://mastodon.social')).not.toBeInTheDocument()
  })
})
