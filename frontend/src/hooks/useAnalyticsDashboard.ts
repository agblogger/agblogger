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

interface AnalyticsDashboardStatsData {
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
}

function formatLocalDate(date: Date): string {
  const year = String(date.getFullYear())
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  start.setDate(start.getDate() - days)
  return {
    start: formatLocalDate(start),
    end: formatLocalDate(end),
  }
}

export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)

  const settingsResult = useSWR<AnalyticsSettings, Error>(
    ['analytics-dashboard-settings'],
    fetchAnalyticsSettings,
  )

  const dashboardResult = useSWR<AnalyticsDashboardStatsData, Error>(
    ['analytics-dashboard', start, end],
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

  const data =
    settingsResult.data !== undefined && dashboardResult.data !== undefined
      ? {
          settings: settingsResult.data,
          ...dashboardResult.data,
        }
      : undefined

  return {
    data,
    settings: settingsResult.data,
    error: settingsResult.error ?? dashboardResult.error,
    isLoading: settingsResult.isLoading || dashboardResult.isLoading,
    mutate: async () => {
      const [settings, stats] = await Promise.all([
        settingsResult.mutate(),
        dashboardResult.mutate(),
      ])
      if (settings === undefined || stats === undefined) {
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
