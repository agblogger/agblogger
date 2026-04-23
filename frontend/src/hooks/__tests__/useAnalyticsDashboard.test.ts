import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { localDateToUtcEnd, localDateToUtcStart } from '@/utils/date'

const mockFetchAnalyticsSettings = vi.fn()
const mockFetchDashboard = vi.fn()
const mockFetchPathReferrers = vi.fn()
const mockFetchBreakdownDetail = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) => mockFetchAnalyticsSettings(...args) as unknown,
  fetchDashboard: (...args: unknown[]) => mockFetchDashboard(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
  fetchBreakdownDetail: (...args: unknown[]) => mockFetchBreakdownDetail(...args) as unknown,
}))

import { useAnalyticsDashboard, usePathReferrers, useBreakdownDetail, isDateRangeValid } from '../useAnalyticsDashboard'
import type {
  AnalyticsSettings,
  DashboardResponse,
  PathReferrersResponse,
  BreakdownDetailResponse,
} from '@/api/client'

const nodeProcess = (globalThis as unknown as {
  process: { env: Record<string, string | undefined> }
}).process

const analyticsSettings: AnalyticsSettings = {
  analytics_enabled: true,
  show_views_on_posts: true,
}

const dashboardResponse: DashboardResponse = {
  stats: { visitors: 500 },
  paths: {
    paths: [
      { path_id: 1, path: '/post/hello', views: 200 },
      { path_id: 2, path: '/post/world', views: 150 },
    ],
  },
  views_over_time: { days: [{ date: '2026-03-19', views: 42 }] },
  browsers: {
    category: 'browsers',
    entries: [
      { name: 'Chrome', count: 700, percent: 70 },
      { name: 'Firefox', count: 300, percent: 30 },
    ],
  },
  operating_systems: {
    category: 'systems',
    entries: [
      { name: 'macOS', count: 600, percent: 60 },
      { name: 'Windows', count: 400, percent: 40 },
    ],
  },
  languages: { category: 'languages', entries: [{ name: 'en', count: 800, percent: 80 }] },
  locations: { category: 'locations', entries: [{ name: 'US', count: 600, percent: 60 }] },
  referrers: { referrers: [{ referrer: 'https://hn.algolia.com', count: 10 }] },
}

const pathReferrers: PathReferrersResponse = {
  path_id: 1,
  referrers: [
    { referrer: 'https://example.com', count: 50 },
    { referrer: 'direct', count: 150 },
  ],
}

const breakdownDetail: BreakdownDetailResponse = {
  category: 'browsers',
  entry_id: 'chrome-1',
  entries: [{ name: 'Chrome 120', count: 500, percent: 100 }],
}

const emptyStats = {
  stats: { visitors: 0 },
  paths: { paths: [] },
  browsers: { category: 'browsers', entries: [] },
  operatingSystems: { category: 'systems', entries: [] },
  languages: { category: 'languages', entries: [] },
  locations: { category: 'locations', entries: [] },
  viewsOverTime: { days: [] },
  referrers: { referrers: [] },
}

describe('useAnalyticsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('fetches dashboard in a single call and returns composite data', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchDashboard.mockResolvedValue(dashboardResponse)

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    expect(mockFetchDashboard).toHaveBeenCalledTimes(1)
    expect(result.current.data).toEqual({
      settings: analyticsSettings,
      stats: dashboardResponse.stats,
      paths: dashboardResponse.paths,
      browsers: dashboardResponse.browsers,
      operatingSystems: dashboardResponse.operating_systems,
      languages: dashboardResponse.languages,
      locations: dashboardResponse.locations,
      viewsOverTime: dashboardResponse.views_over_time,
      referrers: dashboardResponse.referrers,
    })
  })

  it('exposes error when fetchDashboard throws', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchDashboard.mockRejectedValue(new Error('GoatCounter down'))

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.error).toBeDefined()
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.error).toBeInstanceOf(Error)
  })

  it('skips stats fetches when analytics is disabled', async () => {
    const disabledSettings: AnalyticsSettings = {
      analytics_enabled: false,
      show_views_on_posts: true,
    }
    mockFetchAnalyticsSettings.mockResolvedValue(disabledSettings)

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.data).toEqual({
      settings: disabledSettings,
      ...emptyStats,
    })
    expect(result.current.error).toBeUndefined()
    expect(mockFetchDashboard).not.toHaveBeenCalled()
  })

  it('mutate stops stats revalidation after analytics is turned off', async () => {
    mockFetchAnalyticsSettings
      .mockResolvedValueOnce(analyticsSettings)
      .mockResolvedValueOnce({
        analytics_enabled: false,
        show_views_on_posts: true,
      })
    mockFetchDashboard.mockResolvedValue(dashboardResponse)

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    mockFetchDashboard.mockClear()

    await act(async () => {
      await result.current.mutate()
    })

    expect(result.current.data).toEqual({
      settings: {
        analytics_enabled: false,
        show_views_on_posts: true,
      },
      ...emptyStats,
    })
    expect(mockFetchDashboard).not.toHaveBeenCalled()
  })

  it('passes correct start/end timestamps to fetchDashboard', async () => {
    const originalTz = nodeProcess.env['TZ']
    nodeProcess.env['TZ'] = 'Europe/Warsaw'
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-03-25T23:30:00Z'))

    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchDashboard.mockResolvedValue(dashboardResponse)

    try {
      renderHook(() => useAnalyticsDashboard('7d'), {
        wrapper: SWRTestWrapper,
      })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      expect(mockFetchDashboard).toHaveBeenCalledWith(
        localDateToUtcStart('2026-03-19'),
        localDateToUtcEnd('2026-03-26'),
      )
    } finally {
      nodeProcess.env['TZ'] = originalTz
      vi.useRealTimers()
    }
  })

  it('suppresses fetch when custom range has start > end', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)

    const invalidRange = { start: '2026-03-20', end: '2026-03-01' }
    const { result } = renderHook(() => useAnalyticsDashboard(invalidRange), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchDashboard).not.toHaveBeenCalled()
  })

  it('passes custom start/end as UTC timestamps to fetchDashboard', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchDashboard.mockResolvedValue(dashboardResponse)

    const customRange = { start: '2026-01-01', end: '2026-01-31' }
    const { result } = renderHook(() => useAnalyticsDashboard(customRange), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    expect(mockFetchDashboard).toHaveBeenCalledWith(
      localDateToUtcStart('2026-01-01'),
      localDateToUtcEnd('2026-01-31'),
    )
  })
})

describe('isDateRangeValid', () => {
  it('returns true for preset ranges', () => {
    expect(isDateRangeValid('7d')).toBe(true)
    expect(isDateRangeValid('30d')).toBe(true)
    expect(isDateRangeValid('90d')).toBe(true)
  })

  it('returns true when start is empty', () => {
    expect(isDateRangeValid({ start: '', end: '2026-03-20' })).toBe(true)
  })

  it('returns true when end is empty', () => {
    expect(isDateRangeValid({ start: '2026-03-01', end: '' })).toBe(true)
  })

  it('returns true when start equals end', () => {
    expect(isDateRangeValid({ start: '2026-03-01', end: '2026-03-01' })).toBe(true)
  })

  it('returns true when start < end', () => {
    expect(isDateRangeValid({ start: '2026-03-01', end: '2026-03-20' })).toBe(true)
  })

  it('returns false when start > end', () => {
    expect(isDateRangeValid({ start: '2026-03-20', end: '2026-03-01' })).toBe(false)
  })
})

describe('usePathReferrers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches referrers for a given path ID', async () => {
    mockFetchPathReferrers.mockResolvedValue(pathReferrers)

    const { result } = renderHook(() => usePathReferrers(1), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(pathReferrers)
    })

    expect(mockFetchPathReferrers).toHaveBeenCalledWith(1)
  })

  it('does not fetch when pathId is null', async () => {
    const { result } = renderHook(() => usePathReferrers(null), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchPathReferrers).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })
})

describe('useBreakdownDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches breakdown detail when category and entryId are provided', async () => {
    mockFetchBreakdownDetail.mockResolvedValue(breakdownDetail)

    const { result } = renderHook(() => useBreakdownDetail('browsers', 'chrome-1'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(breakdownDetail)
    })

    expect(mockFetchBreakdownDetail).toHaveBeenCalledWith('browsers', 'chrome-1')
  })

  it('does not fetch when category is null', async () => {
    const { result } = renderHook(() => useBreakdownDetail(null, 'chrome-1'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchBreakdownDetail).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })

  it('does not fetch when entryId is null', async () => {
    const { result } = renderHook(() => useBreakdownDetail('browsers', null), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockFetchBreakdownDetail).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })
})
