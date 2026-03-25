import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetchAnalyticsSettings = vi.fn()
const mockUpdateAnalyticsSettings = vi.fn()
const mockFetchTotalStats = vi.fn()
const mockFetchPathHits = vi.fn()
const mockFetchPathReferrers = vi.fn()
const mockFetchBreakdown = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) =>
    mockFetchAnalyticsSettings(...args) as unknown,
  updateAnalyticsSettings: (...args: unknown[]) =>
    mockUpdateAnalyticsSettings(...args) as unknown,
  fetchTotalStats: (...args: unknown[]) => mockFetchTotalStats(...args) as unknown,
  fetchPathHits: (...args: unknown[]) => mockFetchPathHits(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
  fetchBreakdown: (...args: unknown[]) => mockFetchBreakdown(...args) as unknown,
}))

// Recharts uses ResizeObserver — provide a stub in jsdom
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

import AnalyticsPanel from '../AnalyticsPanel'

const DEFAULT_SETTINGS = { analytics_enabled: true, show_views_on_posts: false }

const DEFAULT_STATS = { total_views: 1234, total_unique: 567 }

const DEFAULT_PATHS = {
  paths: [
    { path: '/posts/hello', views: 800, unique: 300 },
    { path: '/posts/world', views: 434, unique: 267 },
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
    if (category === 'browsers') return Promise.resolve(DEFAULT_BROWSERS)
    return Promise.resolve(DEFAULT_SYSTEMS)
  })
  mockFetchPathReferrers.mockResolvedValue({ path_id: 0, referrers: [] })
}

function renderPanel(props: { busy?: boolean; onBusyChange?: (busy: boolean) => void } = {}) {
  const defaultProps = {
    busy: false,
    onBusyChange: vi.fn(),
    ...props,
  }
  return render(<AnalyticsPanel {...defaultProps} />)
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
      expect(screen.getByText('Total Views')).toBeInTheDocument()
    })
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('567')).toBeInTheDocument()
    expect(screen.getByText('Unique Visitors')).toBeInTheDocument()
    expect(screen.getByText('Top Page')).toBeInTheDocument()
    // /posts/hello appears in "Top Page" card AND in table — just check at least one
    expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
  })

  it('renders date range buttons', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Total Views')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'Last 7 days' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Last 30 days' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Last 90 days' })).toBeInTheDocument()
  })

  it('renders toggle switches', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Total Views')).toBeInTheDocument()
    })
    expect(screen.getByRole('switch', { name: /analytics enabled/i })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /show views on posts/i })).toBeInTheDocument()
  })

  it('reflects settings from API in toggle switches', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Total Views')).toBeInTheDocument()
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
      expect(screen.getByText('Total Views')).toBeInTheDocument()
    })

    // Reset call counts after initial load
    const initialCallCount = mockFetchTotalStats.mock.calls.length

    await user.click(screen.getByRole('button', { name: 'Last 30 days' }))

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
      expect(screen.getByText('Total Views')).toBeInTheDocument()
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
      expect(screen.getByText('Total Views')).toBeInTheDocument()
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
      expect(screen.getByText('Total Views')).toBeInTheDocument()
    })

    const analyticsSwitch = screen.getByRole('switch', { name: /analytics enabled/i })
    await user.click(analyticsSwitch)

    await waitFor(() => {
      expect(screen.getByText(/failed to update setting/i)).toBeInTheDocument()
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

  it('renders top pages table with path, views, unique columns', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('Top pages')).toBeInTheDocument()
    })
    // /posts/hello appears in both the summary card and table — use getAllByText
    expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
    expect(screen.getAllByText('/posts/world').length).toBeGreaterThan(0)
    // Views column
    expect(screen.getByText('800')).toBeInTheDocument()
    expect(screen.getByText('434')).toBeInTheDocument()
  })

  it('clicking a page row shows referrer drill-down', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 0,
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

  it('shows "No referrer data" when referrers list is empty', async () => {
    mockFetchPathReferrers.mockResolvedValue({ path_id: 0, referrers: [] })
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
    })

    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('No referrer data for this page.')).toBeInTheDocument()
    })
  })

  it('remains usable when referrer fetch fails', async () => {
    mockFetchPathReferrers.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getAllByText('/posts/hello').length).toBeGreaterThan(0)
    })

    // Click a row — should show the referrer panel with no data message (not crash)
    await user.click(screen.getByRole('button', { name: 'View referrers for /posts/hello' }))

    await waitFor(() => {
      expect(screen.getByText('No referrer data for this page.')).toBeInTheDocument()
    })
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
})
