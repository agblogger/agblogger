import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'

const mockFetchAnalyticsSettings = vi.fn()
const mockUpdateAnalyticsSettings = vi.fn()
const mockFetchTotalStats = vi.fn()
const mockFetchPathHits = vi.fn()
const mockFetchPathReferrers = vi.fn()
const mockFetchBreakdown = vi.fn()
const mockFetchViewsOverTime = vi.fn()
const mockFetchSiteReferrers = vi.fn()
const mockFetchBreakdownDetail = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) =>
    mockFetchAnalyticsSettings(...args) as unknown,
  updateAnalyticsSettings: (...args: unknown[]) =>
    mockUpdateAnalyticsSettings(...args) as unknown,
  fetchTotalStats: (...args: unknown[]) => mockFetchTotalStats(...args) as unknown,
  fetchPathHits: (...args: unknown[]) => mockFetchPathHits(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
  fetchBreakdown: (...args: unknown[]) => mockFetchBreakdown(...args) as unknown,
  fetchViewsOverTime: (...args: unknown[]) => mockFetchViewsOverTime(...args) as unknown,
  fetchSiteReferrers: (...args: unknown[]) => mockFetchSiteReferrers(...args) as unknown,
  fetchBreakdownDetail: (...args: unknown[]) => mockFetchBreakdownDetail(...args) as unknown,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: {},
    HTTPError: MockHTTPError,
  }
})

// Recharts uses ResizeObserver — provide a stub in jsdom
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

import AnalyticsPanel from '../AnalyticsPanel'
import { MockHTTPError } from '@/test/MockHTTPError'

const DEFAULT_SETTINGS = { analytics_enabled: true, show_views_on_posts: false }

const DEFAULT_STATS = { visitors: 567 }

const DEFAULT_PATHS = {
  paths: [
    { path_id: 1, path: '/posts/hello', views: 800 },
    { path_id: 2, path: '/posts/world', views: 434 },
  ],
}

const DEFAULT_BROWSERS = {
  category: 'browsers',
  entries: [
    { name: 'Chrome', count: 500, percent: 72.3 },
    { name: 'Firefox', count: 192, percent: 27.7 },
  ],
}

const DEFAULT_SYSTEMS = {
  category: 'systems',
  entries: [
    { name: 'macOS', count: 400, percent: 57.8 },
    { name: 'Windows', count: 292, percent: 42.2 },
  ],
}

function setupDefaults() {
  mockFetchAnalyticsSettings.mockResolvedValue(DEFAULT_SETTINGS)
  mockFetchTotalStats.mockResolvedValue(DEFAULT_STATS)
  mockFetchPathHits.mockResolvedValue(DEFAULT_PATHS)
  mockFetchBreakdown.mockImplementation((category: string) => {
    const responses: Record<string, unknown> = {
      browsers: DEFAULT_BROWSERS,
      systems: DEFAULT_SYSTEMS,
      languages: { category: 'languages', entries: [{ name: 'English', count: 80, percent: 68.0 }] },
      locations: { category: 'locations', entries: [{ name: 'US', count: 100, percent: 45.0 }] },
      sizes: { category: 'sizes', entries: [{ name: '1920x1080', count: 60, percent: 38.0 }] },
      campaigns: { category: 'campaigns', entries: [] },
    }
    return Promise.resolve(responses[category] ?? { category, entries: [] })
  })
  mockFetchPathReferrers.mockResolvedValue({ path_id: 0, referrers: [] })
  mockFetchViewsOverTime.mockResolvedValue({ days: [] })
  mockFetchSiteReferrers.mockResolvedValue({ referrers: [] })
  mockFetchBreakdownDetail.mockResolvedValue(null)
}

function renderPanel(props: { busy?: boolean; onBusyChange?: (busy: boolean) => void } = {}) {
  const defaultProps = {
    busy: false,
    onBusyChange: vi.fn(),
    ...props,
  }
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <AnalyticsPanel {...defaultProps} />
    </SWRConfig>,
  )
}

describe('AnalyticsPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setupDefaults()
  })

  it('shows loading spinner initially then renders dashboard data', async () => {
    // Use a deferred promise so we can observe the loading state — block all parallel fetches
    let resolveAll!: () => void
    const gate = new Promise<void>((resolve) => {
      resolveAll = resolve
    })
    mockFetchAnalyticsSettings.mockReturnValue(gate.then(() => DEFAULT_SETTINGS))
    mockFetchTotalStats.mockReturnValue(gate.then(() => DEFAULT_STATS))
    mockFetchPathHits.mockReturnValue(gate.then(() => DEFAULT_PATHS))
    mockFetchBreakdown.mockReturnValue(gate.then(() => DEFAULT_BROWSERS))

    renderPanel()
    // While loading, spinner is present
    expect(screen.getByRole('status')).toBeInTheDocument()

    // Resolve all fetches
    resolveAll()

    // After data loads, shows summary cards
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('567')).toBeInTheDocument()
    // "Visitors" appears in summary card and as column header in breakdown tables
    expect(screen.getAllByText('Visitors').length).toBeGreaterThan(0)
    expect(screen.getByText('Top Page')).toBeInTheDocument()
    // /posts/hello appears in "Top Page" card AND in table — just check at least one
    expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
  })

  it('renders date range picker with preset buttons', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: '7d' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '30d' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '90d' })).toBeInTheDocument()
  })

  it('renders toggle switches', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })
    expect(screen.getByRole('switch', { name: /analytics enabled/i })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /show views on posts/i })).toBeInTheDocument()
  })

  it('reflects settings from API in toggle switches', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })
    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    expect(analyticsSwitch).toHaveAttribute('aria-checked', 'true')
    const showViewsSwitch = screen.getByRole('switch', { name: /show views on posts/i })
    expect(showViewsSwitch).toHaveAttribute('aria-checked', 'false')
  })

  it('date range button triggers data refetch', async () => {
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    // Reset call counts after initial load
    const initialCallCount = mockFetchTotalStats.mock.calls.length

    await user.click(screen.getByRole('button', { name: '30d' }))

    await waitFor(() => {
      expect(mockFetchTotalStats.mock.calls.length).toBeGreaterThan(initialCallCount)
    })
    // Should have been called with 30d range dates
    const calls = mockFetchTotalStats.mock.calls
    const lastCall = calls[calls.length - 1] as [string, string]
    expect(lastCall).toHaveLength(2)
    // start date should be roughly 30 days back — just check it's a string date
    expect(typeof lastCall[0]).toBe('string')
  })

  it('toggle switch calls updateAnalyticsSettings', async () => {
    mockUpdateAnalyticsSettings.mockResolvedValue({
      analytics_enabled: false,
      show_views_on_posts: false,
    })
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    await user.click(analyticsSwitch)

    await waitFor(() => {
      expect(mockUpdateAnalyticsSettings).toHaveBeenCalledWith(
        expect.objectContaining({ analytics_enabled: false }),
      )
    })
  })

  it('disables controls while saving toggle', async () => {
    let resolveUpdate: ((value: { analytics_enabled: boolean; show_views_on_posts: boolean }) => void) | undefined
    mockUpdateAnalyticsSettings.mockReturnValue(
      new Promise<{ analytics_enabled: boolean; show_views_on_posts: boolean }>((resolve) => {
        resolveUpdate = resolve
      }),
    )
    const onBusyChange = vi.fn()
    const user = userEvent.setup()
    renderPanel({ onBusyChange })
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    await user.click(analyticsSwitch)

    // While saving, onBusyChange(true) should have been called
    await waitFor(() => {
      expect(onBusyChange).toHaveBeenCalledWith(true)
    })

    resolveUpdate?.({ analytics_enabled: false, show_views_on_posts: false })

    await waitFor(() => {
      expect(onBusyChange).toHaveBeenCalledWith(false)
    })
  })

  it('shows error message when toggle save fails', async () => {
    mockUpdateAnalyticsSettings.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    await user.click(analyticsSwitch)

    await waitFor(() => {
      expect(screen.getByText(/failed to update setting/i)).toBeInTheDocument()
    })
  })

  it('shows session expired message on 401 during handleToggle', async () => {
    mockUpdateAnalyticsSettings.mockRejectedValue(new MockHTTPError(401))
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    await user.click(analyticsSwitch)

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
  })

  it('preserves persisted settings when stats are unavailable', async () => {
    // With Promise.allSettled (Issue 11), individual stats failures fall back to empty/zero
    // data — the panel remains usable and settings are preserved.
    mockFetchAnalyticsSettings.mockResolvedValue({
      analytics_enabled: true,
      show_views_on_posts: true,
    })
    mockFetchTotalStats.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchPathHits.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchBreakdown.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchViewsOverTime.mockRejectedValue(new Error('GoatCounter down'))
    mockUpdateAnalyticsSettings.mockResolvedValue({
      analytics_enabled: false,
      show_views_on_posts: true,
    })
    const user = userEvent.setup()

    renderPanel()

    // Dashboard still loads (with zero data) — not "Analytics unavailable"
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    // Settings are preserved correctly
    expect(screen.getByRole('switch', { name: /analytics enabled/i })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    expect(screen.getByRole('switch', { name: /show views on posts/i })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    await user.click(screen.getByRole('switch', { name: /analytics enabled/i }))

    await waitFor(() => {
      expect(mockUpdateAnalyticsSettings).toHaveBeenCalledWith({
        analytics_enabled: false,
        show_views_on_posts: true,
      })
    })
  })

  it('shows "Analytics unavailable" when all fetches fail', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchAnalyticsSettings.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchTotalStats.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchPathHits.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchBreakdown.mockRejectedValue(new Error('GoatCounter down'))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Analytics unavailable')).toBeInTheDocument()
    })
  })

  it('renders top pages panel with path and views', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top pages')).toBeInTheDocument()
    })
    expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
    expect(screen.getAllByText('/posts/world').length).toBeGreaterThan(0)
    expect(screen.getByText('800')).toBeInTheDocument()
    expect(screen.getByText('434')).toBeInTheDocument()
  })

  it('shows session expired message on 401 during loadDashboard', async () => {
    const authError = new MockHTTPError(401)
    mockFetchAnalyticsSettings.mockRejectedValue(authError)
    mockFetchTotalStats.mockRejectedValue(authError)
    mockFetchPathHits.mockRejectedValue(authError)
    mockFetchBreakdown.mockRejectedValue(authError)
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
    expect(screen.queryByText('Analytics unavailable')).not.toBeInTheDocument()
  })

  it('disables date range buttons and toggle switches when busy={true}', async () => {
    renderPanel({ busy: true })
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: '7d' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '30d' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '90d' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: /analytics enabled/i })).toBeDisabled()
    expect(screen.getByRole('switch', { name: /show views on posts/i })).toBeDisabled()
  })

  it('renders browser and OS section headings', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Browsers')).toBeInTheDocument()
    })
    expect(screen.getByText('Operating Systems')).toBeInTheDocument()
  })

  it('shows empty message when no path data', async () => {
    mockFetchPathHits.mockResolvedValue({ paths: [] })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('No page data for selected range.')).toBeInTheDocument()
    })
  })

  it('shows "—" for top page when no path data', async () => {
    mockFetchPathHits.mockResolvedValue({ paths: [] })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top Page')).toBeInTheDocument()
    })
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders top pages table sorted by views descending', async () => {
    mockFetchPathHits.mockResolvedValue({
      paths: [
        { path_id: 3, path: '/posts/low', views: 50 },
        { path_id: 1, path: '/posts/high', views: 900 },
        { path_id: 2, path: '/posts/mid', views: 300 },
      ],
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top pages')).toBeInTheDocument()
    })

    const rows = screen.getAllByRole('button', { name: /View referrers for/ })
    expect(rows).toHaveLength(3)
    // Rows should appear sorted: high (900), mid (300), low (50)
    expect(rows[0]).toHaveAttribute('aria-label', 'View referrers for /posts/high')
    expect(rows[1]).toHaveAttribute('aria-label', 'View referrers for /posts/mid')
    expect(rows[2]).toHaveAttribute('aria-label', 'View referrers for /posts/low')
  })

  it('renders views over time chart section', async () => {
    mockFetchViewsOverTime.mockResolvedValue({
      days: [
        { date: '2024-01-01', views: 100 },
        { date: '2024-01-02', views: 200 },
      ],
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Views over time')).toBeInTheDocument()
    })
  })

  it('renders top referrers panel', async () => {
    mockFetchSiteReferrers.mockResolvedValue({
      referrers: [{ referrer: 'https://example.com', count: 42 }],
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top referrers')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('https://example.com')).toBeInTheDocument()
    })
  })

  it('renders Locations and Languages breakdown panels', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Locations')).toBeInTheDocument()
    })
    expect(screen.getByText('Languages')).toBeInTheDocument()
  })

  it('renders Screen Sizes and Campaigns breakdown panels', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Screen Sizes')).toBeInTheDocument()
    })
    expect(screen.getByText('Campaigns')).toBeInTheDocument()
  })

  it('renders Export CSV button', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /export csv/i })).toBeInTheDocument()
  })

  it('clicking page row in TopPagesPanel expands inline referrer detail', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 1,
      referrers: [
        { referrer: 'https://hn.algolia.com', count: 42 },
        { referrer: 'direct', count: 18 },
      ],
    })
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
    })

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('https://hn.algolia.com')).toBeInTheDocument()
    })
    expect(screen.getByText('direct')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('custom date range triggers data refetch with custom dates', async () => {
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Page Views')).toBeInTheDocument()
    })

    const initialCallCount = mockFetchTotalStats.mock.calls.length

    const startInput = screen.getByLabelText('Start date')
    await user.type(startInput, '2024-01-01')

    await waitFor(() => {
      expect(mockFetchTotalStats.mock.calls.length).toBeGreaterThan(initialCallCount)
    })
  })
})
