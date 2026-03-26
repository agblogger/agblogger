import api from './client'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  PathReferrersResponse,
  BreakdownResponse,
  BreakdownCategory,
  ViewCountResponse,
} from './client'

export async function fetchAnalyticsSettings(): Promise<AnalyticsSettings> {
  return api.get('admin/analytics/settings').json<AnalyticsSettings>()
}

export async function updateAnalyticsSettings(
  settings: Partial<AnalyticsSettings>,
): Promise<AnalyticsSettings> {
  return api.put('admin/analytics/settings', { json: settings }).json<AnalyticsSettings>()
}

export async function fetchTotalStats(start: string, end: string): Promise<TotalStatsResponse> {
  return api
    .get('admin/analytics/stats/total', { searchParams: { start, end } })
    .json<TotalStatsResponse>()
}

export async function fetchPathHits(start: string, end: string): Promise<PathHitsResponse> {
  return api
    .get('admin/analytics/stats/hits', { searchParams: { start, end } })
    .json<PathHitsResponse>()
}

export async function fetchPathReferrers(pathId: number): Promise<PathReferrersResponse> {
  return api.get(`admin/analytics/stats/hits/${pathId}`).json<PathReferrersResponse>()
}

export async function fetchBreakdown(
  category: BreakdownCategory,
  start: string,
  end: string,
): Promise<BreakdownResponse> {
  return api
    .get(`admin/analytics/stats/${category}`, { searchParams: { start, end } })
    .json<BreakdownResponse>()
}

export async function fetchViewCount(filePath: string): Promise<ViewCountResponse> {
  return api.get(`analytics/views/${filePath}`).json<ViewCountResponse>()
}
