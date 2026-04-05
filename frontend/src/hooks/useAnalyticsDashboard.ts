import useSWR from 'swr'
import {
  fetchAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchBreakdown,
  fetchPathReferrers,
  fetchViewsOverTime,
  fetchSiteReferrers,
  fetchBreakdownDetail,
} from '@/api/analytics'
import { localDateToUtcEnd, localDateToUtcStart } from '@/utils/date'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  BreakdownResponse,
  PathReferrersResponse,
  ViewsOverTimeResponse,
  SiteReferrersResponse,
  BreakdownDetailCategory,
  BreakdownDetailResponse,
} from '@/api/client'

export interface AnalyticsDashboardData {
  settings: AnalyticsSettings
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
  languages: BreakdownResponse
  locations: BreakdownResponse
  sizes: BreakdownResponse
  campaigns: BreakdownResponse
  viewsOverTime: ViewsOverTimeResponse
}

export type DateRangePreset = '7d' | '30d' | '90d'

export interface CustomDateRange {
  start: string // YYYY-MM-DD
  end: string // YYYY-MM-DD
}

export type DateRange = DateRangePreset | CustomDateRange

const RANGE_DAYS: Record<DateRangePreset, number> = { '7d': 7, '30d': 30, '90d': 90 }

interface AnalyticsDashboardStatsData {
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
  languages: BreakdownResponse
  locations: BreakdownResponse
  sizes: BreakdownResponse
  campaigns: BreakdownResponse
  viewsOverTime: ViewsOverTimeResponse
}

function getDisabledDashboardStats(): AnalyticsDashboardStatsData {
  return {
    stats: {
      visitors: 0,
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
    languages: { category: 'languages', entries: [] },
    locations: { category: 'locations', entries: [] },
    sizes: { category: 'sizes', entries: [] },
    campaigns: { category: 'campaigns', entries: [] },
    viewsOverTime: { days: [] },
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
 * Compute UTC start/end instants for the selected local-date range.
 *
 * The browser chooses the local calendar dates, then converts them to explicit
 * UTC timestamps so the backend does not have to infer client timezone.
 */
function getDateRange(range: DateRange): { start: string; end: string } {
  if (typeof range === 'object') {
    return {
      start: localDateToUtcStart(range.start),
      end: localDateToUtcEnd(range.end),
    }
  }
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - RANGE_DAYS[range])
  return {
    start: localDateToUtcStart(formatLocalDate(start)),
    end: localDateToUtcEnd(formatLocalDate(end)),
  }
}

/** Returns false only when a custom range has a non-empty start that is after a non-empty end. */
export function isDateRangeValid(range: DateRange): boolean {
  if (typeof range !== 'object') return true
  const { start, end } = range
  return start === '' || end === '' || start <= end
}

/**
 * Composite SWR hook that fetches analytics settings first, then conditionally
 * fetches stats (total, paths, browsers, OS, languages, locations, sizes,
 * campaigns, views-over-time) in parallel when analytics is enabled.
 * Returns zeroed-out data when analytics is disabled rather than triggering fetches.
 * Individual fetch failures fall back to empty/zero data instead of rejecting the whole batch.
 */
export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)
  const rangeValid = isDateRangeValid(range)

  const settingsResult = useSWR<AnalyticsSettings, Error>(
    ['analytics-dashboard-settings'],
    fetchAnalyticsSettings,
  )
  const analyticsEnabled = settingsResult.data?.analytics_enabled ?? null

  const dashboardResult = useSWR<AnalyticsDashboardStatsData, Error>(
    analyticsEnabled === true && rangeValid ? ['analytics-dashboard', start, end] : null,
    async () => {
      function fulfilled<T>(r: PromiseSettledResult<T>): T | undefined {
        return r.status === 'fulfilled' ? r.value : undefined
      }

      const [
        statsResult,
        pathsResult,
        browsersResult,
        osResult,
        languagesResult,
        locationsResult,
        sizesResult,
        campaignsResult,
        viewsOverTimeResult,
      ] = await Promise.allSettled([
        fetchTotalStats(start, end),
        fetchPathHits(start, end),
        fetchBreakdown('browsers', start, end),
        fetchBreakdown('systems', start, end),
        fetchBreakdown('languages', start, end),
        fetchBreakdown('locations', start, end),
        fetchBreakdown('sizes', start, end),
        fetchBreakdown('campaigns', start, end),
        fetchViewsOverTime(start, end),
      ])

      const stats = fulfilled(statsResult) ?? { visitors: 0 }
      const paths = fulfilled(pathsResult) ?? { paths: [] }
      const browsersData = fulfilled(browsersResult) ?? { category: 'browsers' as const, entries: [] }
      const osData = fulfilled(osResult) ?? { category: 'systems' as const, entries: [] }
      const languagesData = fulfilled(languagesResult) ?? { category: 'languages' as const, entries: [] }
      const locationsData = fulfilled(locationsResult) ?? { category: 'locations' as const, entries: [] }
      const sizesData = fulfilled(sizesResult) ?? { category: 'sizes' as const, entries: [] }
      const campaignsData = fulfilled(campaignsResult) ?? { category: 'campaigns' as const, entries: [] }
      const viewsOverTimeData = fulfilled(viewsOverTimeResult) ?? { days: [] }

      return {
        stats,
        paths,
        browsers: browsersData,
        operatingSystems: osData,
        languages: languagesData,
        locations: locationsData,
        sizes: sizesData,
        campaigns: campaignsData,
        viewsOverTime: viewsOverTimeData,
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

export function useSiteReferrers(range: DateRange, enabled: boolean) {
  const { start, end } = getDateRange(range)
  const rangeValid = isDateRangeValid(range)
  return useSWR<SiteReferrersResponse, Error>(
    enabled && rangeValid ? ['site-referrers', start, end] : null,
    () => fetchSiteReferrers(start, end),
  )
}

export function useBreakdownDetail(
  category: BreakdownDetailCategory | null,
  entryId: string | null,
) {
  return useSWR<BreakdownDetailResponse, Error>(
    category !== null && entryId !== null ? ['breakdown-detail', category, entryId] : null,
    ([, cat, id]: [string, BreakdownDetailCategory, string]) => fetchBreakdownDetail(cat, id),
  )
}
