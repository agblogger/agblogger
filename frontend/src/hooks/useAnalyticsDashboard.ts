import useSWR from 'swr'
import {
  fetchAnalyticsSettings,
  fetchDashboard,
  fetchPathReferrers,
  fetchBreakdownDetail,
} from '@/api/analytics'
import { localDateToUtcEnd, localDateToUtcStart } from '@/utils/date'
import type {
  AnalyticsSettings,
  DashboardResponse,
  PathReferrersResponse,
  BreakdownDetailCategory,
  BreakdownDetailResponse,
  BreakdownResponse,
  PathHitsResponse,
  SiteReferrersResponse,
  TotalStatsResponse,
  ViewsOverTimeResponse,
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
  referrers: SiteReferrersResponse
}

export type DateRangePreset = '7d' | '30d' | '90d'

export interface CustomDateRange {
  start: string // YYYY-MM-DD
  end: string // YYYY-MM-DD
}

export type DateRange = DateRangePreset | CustomDateRange

const RANGE_DAYS: Record<DateRangePreset, number> = { '7d': 7, '30d': 30, '90d': 90 }

function getDisabledDashboardStats() {
  return {
    stats: { visitors: 0 },
    paths: { paths: [] },
    browsers: { category: 'browsers' as const, entries: [] },
    operatingSystems: { category: 'systems' as const, entries: [] },
    languages: { category: 'languages' as const, entries: [] },
    locations: { category: 'locations' as const, entries: [] },
    sizes: { category: 'sizes' as const, entries: [] },
    campaigns: { category: 'campaigns' as const, entries: [] },
    viewsOverTime: { days: [] },
    referrers: { referrers: [] },
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

function dashboardToData(
  settings: AnalyticsSettings,
  dashboard: DashboardResponse,
): AnalyticsDashboardData {
  return {
    settings,
    stats: dashboard.stats,
    paths: dashboard.paths,
    viewsOverTime: dashboard.views_over_time,
    browsers: dashboard.browsers,
    operatingSystems: dashboard.operating_systems,
    languages: dashboard.languages,
    locations: dashboard.locations,
    sizes: dashboard.sizes,
    campaigns: dashboard.campaigns,
    referrers: dashboard.referrers,
  }
}

/**
 * Composite SWR hook that fetches analytics settings first, then fetches all
 * dashboard stats via a single backend request when analytics is enabled.
 * The backend fetches GoatCounter endpoints sequentially to stay within rate
 * limits. Returns zeroed-out data when analytics is disabled rather than
 * triggering fetches.
 */
export function useAnalyticsDashboard(range: DateRange) {
  const { start, end } = getDateRange(range)
  const rangeValid = isDateRangeValid(range)

  const settingsResult = useSWR<AnalyticsSettings, Error>(
    ['analytics-dashboard-settings'],
    fetchAnalyticsSettings,
  )
  const analyticsEnabled = settingsResult.data?.analytics_enabled ?? null

  const dashboardResult = useSWR<DashboardResponse, Error>(
    analyticsEnabled === true && rangeValid ? ['analytics-dashboard', start, end] : null,
    () => fetchDashboard(start, end),
  )

  const disabled = settingsResult.data?.analytics_enabled === false

  const data: AnalyticsDashboardData | undefined =
    settingsResult.data !== undefined
      ? disabled
        ? { settings: settingsResult.data, ...getDisabledDashboardStats() }
        : dashboardResult.data !== undefined
          ? dashboardToData(settingsResult.data, dashboardResult.data)
          : undefined
      : undefined

  return {
    data,
    settings: settingsResult.data,
    error: settingsResult.error ?? (disabled ? undefined : dashboardResult.error),
    isLoading:
      settingsResult.isLoading ||
      (analyticsEnabled === true && dashboardResult.isLoading),
    // Sequential by design: the dashboard fetch is conditional on analytics being enabled,
    // so settings must be resolved first to avoid an unnecessary dashboard request.
    mutate: async () => {
      const settings = await settingsResult.mutate()
      if (settings === undefined) return undefined
      if (!settings.analytics_enabled) {
        return { settings, ...getDisabledDashboardStats() }
      }
      const dashboard = await dashboardResult.mutate()
      if (dashboard === undefined) return undefined
      return dashboardToData(settings, dashboard)
    },
  }
}

export function usePathReferrers(pathId: number | null) {
  return useSWR<PathReferrersResponse, Error>(
    pathId !== null ? ['pathReferrers', pathId] : null,
    ([, id]: [string, number]) => fetchPathReferrers(id),
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
