import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRTestWrapper } from '@/test/swrWrapper'

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

describe('useAnalyticsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
      browsers: browsersData.entries,
      operatingSystems: osData.entries,
    })
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
