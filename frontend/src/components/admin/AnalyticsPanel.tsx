import { useMemo, useState } from 'react'
import { BarChart2, Loader2 } from 'lucide-react'

import { updateAnalyticsSettings } from '@/api/analytics'
import { HTTPError } from '@/api/client'
import type { AnalyticsSettings } from '@/api/client'
import type { DateRange } from '@/hooks/useAnalyticsDashboard'
import { useAnalyticsDashboard } from '@/hooks/useAnalyticsDashboard'
import DateRangePicker from './analytics/DateRangePicker'
import ExportButton from './analytics/ExportButton'
import ViewsOverTimeChart from './analytics/ViewsOverTimeChart'
import TopPagesPanel from './analytics/TopPagesPanel'
import TopReferrersPanel from './analytics/TopReferrersPanel'
import BreakdownBarChart from './analytics/BreakdownBarChart'
import BreakdownTable from './analytics/BreakdownTable'

interface AnalyticsPanelProps {
  busy: boolean
  onBusyChange: (busy: boolean) => void
}

function ToggleSwitch({
  id,
  label,
  checked,
  disabled,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  disabled: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2 cursor-pointer select-none">
      <span className="text-sm text-ink" id={`${id}-label`}>{label}</span>
      <button
        id={id}
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex w-10 h-5 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-50 disabled:cursor-not-allowed ${
          checked ? 'bg-accent' : 'bg-border'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

export default function AnalyticsPanel({ busy, onBusyChange }: AnalyticsPanelProps) {
  const [dateRange, setDateRange] = useState<DateRange>('7d')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const {
    data,
    settings: persistedSettings,
    error: dashboardError,
    isLoading: loading,
    mutate: dashboardMutate,
  } = useAnalyticsDashboard(dateRange)

  const is401 = dashboardError instanceof HTTPError && dashboardError.response.status === 401
  const unavailable = dashboardError !== undefined && !is401
  const sessionExpiredError = is401 ? 'Session expired. Please log in again.' : null

  const settings: AnalyticsSettings = persistedSettings ?? {
    analytics_enabled: false,
    show_views_on_posts: false,
  }
  const settingsLoaded = persistedSettings !== undefined

  // GoatCounter's per-path "count" is unique visitors per path, so summing
  // across paths gives "total page views" — distinct from the site-wide
  // "Visitors" metric (GoatCounter's "total") which deduplicates across paths.
  const sortedPaths = useMemo(
    () => [...(data?.paths.paths ?? [])].sort((a, b) => b.views - a.views),
    [data],
  )
  const pageViews = useMemo(
    () => sortedPaths.reduce((sum, p) => sum + p.views, 0),
    [sortedPaths],
  )
  const topPage = sortedPaths.length > 0 && sortedPaths[0] ? sortedPaths[0].path : '—'

  async function handleToggle(field: keyof AnalyticsSettings, value: boolean) {
    setSaving(true)
    onBusyChange(true)
    setSaveError(null)
    try {
      await updateAnalyticsSettings({ ...settings, [field]: value })
      void dashboardMutate()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setSaveError('Session expired. Please log in again.')
      } else {
        setSaveError('Failed to update setting. Please try again.')
      }
    } finally {
      setSaving(false)
      onBusyChange(false)
    }
  }

  const allBusy = busy || saving
  const displayError = saveError ?? sessionExpiredError

  return (
    <div className="space-y-6">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <DateRangePicker value={dateRange} onChange={setDateRange} disabled={allBusy || loading} />
        <div className="flex flex-wrap items-center gap-6">
          <ToggleSwitch
            id="analytics-enabled"
            label="Analytics enabled"
            checked={settings.analytics_enabled}
            disabled={allBusy || loading || !settingsLoaded}
            onChange={(value) => void handleToggle('analytics_enabled', value)}
          />
          <ToggleSwitch
            id="show-views-on-posts"
            label="Show views on posts"
            checked={settings.show_views_on_posts}
            disabled={allBusy || loading || !settingsLoaded}
            onChange={(value) => void handleToggle('show_views_on_posts', value)}
          />
          <ExportButton disabled={allBusy || loading || !settings.analytics_enabled} />
        </div>
      </div>

      {displayError !== null && (
        <p className="text-sm text-red-600 dark:text-red-400">{displayError}</p>
      )}

      {/* Content area */}
      {loading ? (
        <div className="flex items-center justify-center py-16" aria-label="Loading" role="status">
          <Loader2 size={24} className="text-accent animate-spin" aria-hidden="true" />
        </div>
      ) : unavailable ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BarChart2 size={32} className="text-muted mb-3" />
          <p className="text-ink font-medium">Analytics unavailable</p>
          <p className="text-muted text-sm mt-1">
            GoatCounter may be unreachable. Check your analytics configuration.
          </p>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-surface border border-border rounded-lg px-5 py-4">
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Page Views</p>
              <p className="text-2xl font-semibold text-ink">{pageViews.toLocaleString()}</p>
            </div>
            <div className="bg-surface border border-border rounded-lg px-5 py-4">
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Visitors</p>
              <p className="text-2xl font-semibold text-ink">{(data?.stats.visitors ?? 0).toLocaleString()}</p>
            </div>
            <div className="bg-surface border border-border rounded-lg px-5 py-4">
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Top Page</p>
              <p className="text-sm font-medium text-ink truncate" title={topPage}>
                {topPage}
              </p>
            </div>
          </div>

          {/* Views over time */}
          <ViewsOverTimeChart days={data?.viewsOverTime.days ?? []} />

          {/* Top pages + Top referrers side by side */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <TopPagesPanel paths={data?.paths.paths ?? []} />
            <TopReferrersPanel
              referrers={data?.referrers.referrers ?? []}
              isLoading={loading}
            />
          </div>

          {/* Browsers + OS */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <BreakdownBarChart title="Browsers" entries={data?.browsers.entries ?? []} drillDownCategory="browsers" />
            <BreakdownBarChart title="Operating Systems" entries={data?.operatingSystems.entries ?? []} drillDownCategory="systems" />
          </div>

          {/* Locations + Languages */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <BreakdownTable title="Locations" nameLabel="Country" entries={data?.locations.entries ?? []} />
            <BreakdownTable title="Languages" nameLabel="Language" entries={data?.languages.entries ?? []} />
          </div>

          {/* Screen Sizes + Campaigns */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <BreakdownBarChart title="Screen Sizes" entries={data?.sizes.entries ?? []} />
            <BreakdownTable title="Campaigns" nameLabel="Campaign" entries={data?.campaigns.entries ?? []} />
          </div>
        </>
      )}
    </div>
  )
}
