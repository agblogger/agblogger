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
  BreakdownEntry,
  PathReferrersResponse,
} from '@/api/client'

export interface AnalyticsDashboardData {
  settings: AnalyticsSettings
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownEntry[]
  operatingSystems: BreakdownEntry[]
}

type DateRange = '7d' | '30d' | '90d'

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  start.setDate(start.getDate() - days)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  }
}

export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)
  return useSWR<AnalyticsDashboardData>(
    ['analytics-dashboard', start, end],
    async () => {
      const [settings, stats, paths, browsersData, osData] = await Promise.all([
        fetchAnalyticsSettings(),
        fetchTotalStats(start, end),
        fetchPathHits(start, end),
        fetchBreakdown('browsers', start, end),
        fetchBreakdown('systems', start, end),
      ])
      return {
        settings,
        stats,
        paths,
        browsers: browsersData.entries,
        operatingSystems: osData.entries,
      }
    },
  )
}

export function usePathReferrers(pathId: number | null) {
  return useSWR<PathReferrersResponse>(
    pathId !== null ? ['pathReferrers', pathId] : null,
    ([, id]: [string, number]) => fetchPathReferrers(id),
  )
}
