import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'
import { localDateToUtcEnd, localDateToUtcStart } from '@/utils/date'

const mockFetchAnalyticsSettings = vi.fn()
const mockFetchTotalStats = vi.fn()
const mockFetchPathHits = vi.fn()
const mockFetchBreakdown = vi.fn()
const mockFetchPathReferrers = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchAnalyticsSettings: (...args: unknown[]) => mockFetchAnalyticsSettings(...args) as unknown,
  fetchTotalStats: (...args: unknown[]) => mockFetchTotalStats(...args) as unknown,
  fetchPathHits: (...args: unknown[]) => mockFetchPathHits(...args) as unknown,
  fetchBreakdown: (...args: unknown[]) => mockFetchBreakdown(...args) as unknown,
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
}))

import { useAnalyticsDashboard, usePathReferrers } from '../useAnalyticsDashboard'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  BreakdownResponse,
  PathReferrersResponse,
} from '@/api/client'

const nodeProcess = (globalThis as unknown as {
  process: { env: Record<string, string | undefined> }
}).process

const analyticsSettings: AnalyticsSettings = {
  analytics_enabled: true,
  show_views_on_posts: true,
}

const totalStats: TotalStatsResponse = {
  total_views: 1000,
  total_unique: 500,
}

const pathHits: PathHitsResponse = {
  paths: [
    { path_id: 1, path: '/post/hello', views: 200, unique: 100 },
    { path_id: 2, path: '/post/world', views: 150, unique: 80 },
  ],
}

const browsersData: BreakdownResponse = {
  category: 'browsers',
  entries: [
    { name: 'Chrome', count: 700, percent: 70 },
    { name: 'Firefox', count: 300, percent: 30 },
  ],
}

const osData: BreakdownResponse = {
  category: 'systems',
  entries: [
    { name: 'macOS', count: 600, percent: 60 },
    { name: 'Windows', count: 400, percent: 40 },
  ],
}

const pathReferrers: PathReferrersResponse = {
  path_id: 1,
  referrers: [
    { referrer: 'https://example.com', count: 50 },
    { referrer: 'direct', count: 150 },
  ],
}

const emptyStats = {
  stats: { total_views: 0, total_unique: 0 },
  paths: { paths: [] },
  browsers: { category: 'browsers', entries: [] },
  operatingSystems: { category: 'systems', entries: [] },
}

describe('useAnalyticsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('fetches all 5 resources in parallel and returns composite data', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchTotalStats.mockResolvedValue(totalStats)
    mockFetchPathHits.mockResolvedValue(pathHits)
    mockFetchBreakdown.mockImplementation((category: string) => {
      if (category === 'browsers') return Promise.resolve(browsersData)
      if (category === 'systems') return Promise.resolve(osData)
      return Promise.reject(new Error(`Unexpected category: ${category}`))
    })

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    expect(result.current.data).toEqual({
      settings: analyticsSettings,
      stats: totalStats,
      paths: pathHits,
      browsers: browsersData,
      operatingSystems: osData,
    })
  })

  it('returns error when a fetch call rejects', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchTotalStats.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchPathHits.mockResolvedValue(pathHits)
    mockFetchBreakdown.mockImplementation((category: string) => {
      if (category === 'browsers') return Promise.resolve(browsersData)
      if (category === 'systems') return Promise.resolve(osData)
      return Promise.reject(new Error(`Unexpected category: ${category}`))
    })

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.error).toBeDefined()
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.error?.message).toBe('GoatCounter down')
  })

  it('preserves settings when stats fetches fail', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchTotalStats.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchPathHits.mockRejectedValue(new Error('GoatCounter down'))
    mockFetchBreakdown.mockRejectedValue(new Error('GoatCounter down'))

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.error).toBeDefined()
    })

    expect(result.current.settings).toEqual(analyticsSettings)
    expect(result.current.error?.message).toBe('GoatCounter down')
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
    expect(mockFetchTotalStats).not.toHaveBeenCalled()
    expect(mockFetchPathHits).not.toHaveBeenCalled()
    expect(mockFetchBreakdown).not.toHaveBeenCalled()
  })

  it('mutate stops stats revalidation after analytics is turned off', async () => {
    mockFetchAnalyticsSettings
      .mockResolvedValueOnce(analyticsSettings)
      .mockResolvedValueOnce({
        analytics_enabled: false,
        show_views_on_posts: true,
      })
    mockFetchTotalStats.mockResolvedValue(totalStats)
    mockFetchPathHits.mockResolvedValue(pathHits)
    mockFetchBreakdown.mockImplementation((category: string) => {
      if (category === 'browsers') return Promise.resolve(browsersData)
      if (category === 'systems') return Promise.resolve(osData)
      return Promise.reject(new Error(`Unexpected category: ${category}`))
    })

    const { result } = renderHook(() => useAnalyticsDashboard('7d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    mockFetchTotalStats.mockClear()
    mockFetchPathHits.mockClear()
    mockFetchBreakdown.mockClear()

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
    expect(mockFetchTotalStats).not.toHaveBeenCalled()
    expect(mockFetchPathHits).not.toHaveBeenCalled()
    expect(mockFetchBreakdown).not.toHaveBeenCalled()
  })

  it('calls fetchBreakdown twice — once for browsers and once for systems', async () => {
    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchTotalStats.mockResolvedValue(totalStats)
    mockFetchPathHits.mockResolvedValue(pathHits)
    mockFetchBreakdown.mockImplementation((category: string) => {
      if (category === 'browsers') return Promise.resolve(browsersData)
      if (category === 'systems') return Promise.resolve(osData)
      return Promise.reject(new Error(`Unexpected category: ${category}`))
    })

    const { result } = renderHook(() => useAnalyticsDashboard('30d'), {
      wrapper: SWRTestWrapper,
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })

    expect(mockFetchBreakdown).toHaveBeenCalledTimes(2)
    expect(mockFetchBreakdown).toHaveBeenCalledWith('browsers', expect.any(String), expect.any(String))
    expect(mockFetchBreakdown).toHaveBeenCalledWith('systems', expect.any(String), expect.any(String))
  })

  it('formats dashboard ranges as UTC timestamps for the selected local calendar dates', async () => {
    const originalTz = nodeProcess.env['TZ']
    nodeProcess.env['TZ'] = 'Europe/Warsaw'
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-03-25T23:30:00Z'))

    mockFetchAnalyticsSettings.mockResolvedValue(analyticsSettings)
    mockFetchTotalStats.mockResolvedValue(totalStats)
    mockFetchPathHits.mockResolvedValue(pathHits)
    mockFetchBreakdown.mockImplementation((category: string) => {
      if (category === 'browsers') return Promise.resolve(browsersData)
      if (category === 'systems') return Promise.resolve(osData)
      return Promise.reject(new Error(`Unexpected category: ${category}`))
    })

    try {
      renderHook(() => useAnalyticsDashboard('7d'), {
        wrapper: SWRTestWrapper,
      })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      expect(mockFetchTotalStats).toHaveBeenCalledWith(
        localDateToUtcStart('2026-03-19'),
        localDateToUtcEnd('2026-03-26'),
      )
      expect(mockFetchPathHits).toHaveBeenCalledWith(
        localDateToUtcStart('2026-03-19'),
        localDateToUtcEnd('2026-03-26'),
      )
      expect(mockFetchBreakdown).toHaveBeenCalledWith(
        'browsers',
        localDateToUtcStart('2026-03-19'),
        localDateToUtcEnd('2026-03-26'),
      )
      expect(mockFetchBreakdown).toHaveBeenCalledWith(
        'systems',
        localDateToUtcStart('2026-03-19'),
        localDateToUtcEnd('2026-03-26'),
      )
    } finally {
      nodeProcess.env['TZ'] = originalTz
      vi.useRealTimers()
    }
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
