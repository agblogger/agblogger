import api from './client'
import type {
  AnalyticsSettings,
  PathReferrersResponse,
  ViewCountResponse,
  BreakdownDetailCategory,
  BreakdownDetailResponse,
  DashboardResponse,
} from './client'

export async function fetchAnalyticsSettings(): Promise<AnalyticsSettings> {
  return api.get('admin/analytics/settings').json<AnalyticsSettings>()
}

export async function updateAnalyticsSettings(
  settings: Partial<AnalyticsSettings>,
): Promise<AnalyticsSettings> {
  return api.put('admin/analytics/settings', { json: settings }).json<AnalyticsSettings>()
}

export async function fetchPathReferrers(pathId: number): Promise<PathReferrersResponse> {
  return api.get(`admin/analytics/stats/hits/${pathId}`).json<PathReferrersResponse>()
}

/** Fetch public view count. Accepts a bare slug or canonical file path (e.g., "posts/hello/index.md"). */
export async function fetchViewCount(pathOrSlug: string): Promise<ViewCountResponse> {
  return api.get(`analytics/views/${pathOrSlug}`).json<ViewCountResponse>()
}

export async function fetchDashboard(start: string, end: string): Promise<DashboardResponse> {
  return api
    .get('admin/analytics/dashboard', { searchParams: { start, end } })
    .json<DashboardResponse>()
}

export async function fetchBreakdownDetail(
  category: BreakdownDetailCategory,
  entryId: string,
): Promise<BreakdownDetailResponse> {
  return api
    .get(`admin/analytics/stats/${category}/${entryId}`)
    .json<BreakdownDetailResponse>()
}
