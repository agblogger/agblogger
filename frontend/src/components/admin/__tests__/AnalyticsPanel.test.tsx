import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'

const mockFetchAnalyticsSettings = vi.fn()
const mockUpdateAnalyticsSettings = vi.fn()
const mockFetchDashboard = vi.fn()
const mockFetchPathReferrers = vi.fn()
const mockFetchBreakdownDetail = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) =>
    mockFetchAnalyticsSettings(...args) as unknown,
  updateAnalyticsSettings: (...args: unknown[]) =>
    mockUpdateAnalyticsSettings(...args) as unknown,
  fetchDashboard: (...args: unknown[]) => mockFetchDashboard(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
  fetchSiteReferrers: () => Promise.resolve({ referrers: [] }),
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

const DEFAULT_DASHBOARD = {
  stats: { visitors: 567 },
  paths: {
    paths: [
      { path_id: 1, path: '/posts/hello', views: 800 },
      { path_id: 2, path: '/posts/world', views: 434 },
    ],
  },
  views_over_time: { days: [] },
  browsers: {
    category: 'browsers',
    entries: [
      { name: 'Chrome', count: 500, percent: 72.3 },
      { name: 'Firefox', count: 192, percent: 27.7 },
    ],
  },
  operating_systems: {
    category: 'systems',
    entries: [
      { name: 'macOS', count: 400, percent: 57.8 },
      { name: 'Windows', count: 292, percent: 42.2 },
    ],
  },
  languages: { category: 'languages', entries: [{ name: 'English', count: 80, percent: 68.0 }] },
  locations: { category: 'locations', entries: [{ name: 'US', count: 100, percent: 45.0 }] },
  sizes: { category: 'sizes', entries: [{ name: '1920x1080', count: 60, percent: 38.0 }] },
  campaigns: { category: 'campaigns', entries: [] },
  referrers: { referrers: [] },
}

function setupDefaults() {
  mockFetchAnalyticsSettings.mockResolvedValue(DEFAULT_SETTINGS)
  mockFetchDashboard.mockResolvedValue(DEFAULT_DASHBOARD)
  mockFetchPathReferrers.mockResolvedValue({ path_id: 0, referrers: [] })
  mockFetchBreakdownDetail.mockResolvedValue({ category: 'browsers', entry_id: 'chrome', entries: [] })
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
    // Use a deferred promise so we can observe the loading state
    let resolveSettings!: () => void
    const settingsGate = new Promise<void>((resolve) => {
      resolveSettings = resolve
    })
    mockFetchAnalyticsSettings.mockReturnValue(settingsGate.then(() => DEFAULT_SETTINGS))
    mockFetchDashboard.mockResolvedValue(DEFAULT_DASHBOARD)

    renderPanel()
    // While loading, spinner is present
    expect(screen.getByRole('status')).toBeInTheDocument()

    // Resolve settings fetch
    resolveSettings()

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

    const initialCallCount = mockFetchDashboard.mock.calls.length

    await user.click(screen.getByRole('button', { name: '30d' }))

    await waitFor(() => {
      expect(mockFetchDashboard.mock.calls.length).toBeGreaterThan(initialCallCount)
    })
    // fetchDashboard should be called with (start, end) strings
    const calls = mockFetchDashboard.mock.calls
    const lastCall = calls[calls.length - 1] as [string, string]
    expect(lastCall).toHaveLength(2)
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

  it('preserves persisted settings when dashboard returns zero data', async () => {
    // Backend returns empty defaults when GoatCounter partially fails —
    // the panel remains usable and settings are preserved.
    mockFetchAnalyticsSettings.mockResolvedValue({
      analytics_enabled: true,
      show_views_on_posts: true,
    })
    mockFetchDashboard.mockResolvedValue({
      ...DEFAULT_DASHBOARD,
      stats: { visitors: 0 },
      paths: { paths: [] },
      views_over_time: { days: [] },
    })
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
    mockFetchDashboard.mockResolvedValue({ ...DEFAULT_DASHBOARD, paths: { paths: [] } })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('No page data for selected range.')).toBeInTheDocument()
    })
  })

  it('shows "—" for top page when no path data', async () => {
    mockFetchDashboard.mockResolvedValue({ ...DEFAULT_DASHBOARD, paths: { paths: [] } })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top Page')).toBeInTheDocument()
    })
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders top pages table sorted by views descending', async () => {
    mockFetchDashboard.mockResolvedValue({
      ...DEFAULT_DASHBOARD,
      paths: {
        paths: [
          { path_id: 3, path: '/posts/low', views: 50 },
          { path_id: 1, path: '/posts/high', views: 900 },
          { path_id: 2, path: '/posts/mid', views: 300 },
        ],
      },
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
    mockFetchDashboard.mockResolvedValue({
      ...DEFAULT_DASHBOARD,
      views_over_time: {
        days: [
          { date: '2024-01-01', views: 100 },
          { date: '2024-01-02', views: 200 },
        ],
      },
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Views over time')).toBeInTheDocument()
    })
  })

  it('renders top referrers panel with referrers from dashboard', async () => {
    mockFetchDashboard.mockResolvedValue({
      ...DEFAULT_DASHBOARD,
      referrers: { referrers: [{ referrer: 'https://example.com', count: 42 }] },
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

    const initialCallCount = mockFetchDashboard.mock.calls.length

    const startInput = screen.getByLabelText('Start date')
    await user.type(startInput, '2024-01-01')

    await waitFor(() => {
      expect(mockFetchDashboard.mock.calls.length).toBeGreaterThan(initialCallCount)
    })
  })
})
