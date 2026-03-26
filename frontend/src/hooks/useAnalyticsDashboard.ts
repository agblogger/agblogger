import useSWR from 'swr'
import {
  fetchAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchBreakdown,
  fetchPathReferrers,
} from '@/api/analytics'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  BreakdownResponse,
  PathReferrersResponse,
} from '@/api/client'

export interface AnalyticsDashboardData {
  settings: AnalyticsSettings
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
}

export type DateRange = '7d' | '30d' | '90d'

const RANGE_DAYS: Record<DateRange, number> = { '7d': 7, '30d': 30, '90d': 90 }

interface AnalyticsDashboardStatsData {
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
}

function getDisabledDashboardStats(): AnalyticsDashboardStatsData {
  return {
    stats: {
      total_views: 0,
      total_unique: 0,
    },
    paths: {
      paths: [],
    },
    browsers: {
      category: 'browsers',
      entries: [],
    },
    operatingSystems: {
      category: 'systems',
      entries: [],
    },
  }
}

/** Format a Date as YYYY-MM-DD in the browser's local timezone (not UTC). */
function formatLocalDate(date: Date): string {
  const year = String(date.getFullYear())
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * Compute start/end date strings for a given range.
 *
 * Dates are intentionally computed in the browser's local timezone so the
 * dashboard aligns with the user's calendar day, not UTC midnight.
 */
function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - RANGE_DAYS[range])
  return {
    start: formatLocalDate(start),
    end: formatLocalDate(end),
  }
}

/**
 * Composite SWR hook that fetches analytics settings first, then conditionally
 * fetches stats (total, paths, browsers, OS) in parallel when analytics is enabled.
 * Returns zeroed-out data when analytics is disabled rather than triggering fetches.
 */
export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)

  const settingsResult = useSWR<AnalyticsSettings, Error>(
    ['analytics-dashboard-settings'],
    fetchAnalyticsSettings,
  )
  const analyticsEnabled = settingsResult.data?.analytics_enabled ?? null

  const dashboardResult = useSWR<AnalyticsDashboardStatsData, Error>(
    analyticsEnabled === true ? ['analytics-dashboard', start, end] : null,
    async () => {
      const [stats, paths, browsersData, osData] = await Promise.all([
        fetchTotalStats(start, end),
        fetchPathHits(start, end),
        fetchBreakdown('browsers', start, end),
        fetchBreakdown('systems', start, end),
      ])
      return {
        stats,
        paths,
        browsers: browsersData,
        operatingSystems: osData,
      }
    },
  )
  const statsData =
    settingsResult.data?.analytics_enabled === false
      ? getDisabledDashboardStats()
      : dashboardResult.data

  const data: AnalyticsDashboardData | undefined =
    settingsResult.data !== undefined && statsData !== undefined
      ? {
          settings: settingsResult.data,
          ...statsData,
        }
      : undefined

  return {
    data,
    settings: settingsResult.data,
    error:
      settingsResult.error ??
      (settingsResult.data?.analytics_enabled === false ? undefined : dashboardResult.error),
    isLoading:
      settingsResult.isLoading ||
      (settingsResult.data?.analytics_enabled === true && dashboardResult.isLoading),
    mutate: async () => {
      const settings = await settingsResult.mutate()
      if (settings === undefined) {
        return undefined
      }
      if (!settings.analytics_enabled) {
        return {
          settings,
          ...getDisabledDashboardStats(),
        }
      }
      const stats = await dashboardResult.mutate()
      if (stats === undefined) {
        return undefined
      }
      return {
        settings,
        ...stats,
      }
    },
  }
}

export function usePathReferrers(pathId: number | null) {
  return useSWR<PathReferrersResponse, Error>(
    pathId !== null ? ['pathReferrers', pathId] : null,
    ([, id]: [string, number]) => fetchPathReferrers(id),
  )
}
