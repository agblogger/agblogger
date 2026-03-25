import { useEffect, useRef, useState } from 'react'
import { BarChart2, Loader2 } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

import {
  fetchAnalyticsSettings,
  updateAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchPathReferrers,
  fetchBreakdown,
} from '@/api/analytics'
import type { AnalyticsSettings, PathHit, ReferrerEntry, BreakdownEntry } from '@/api/client'

interface AnalyticsPanelProps {
  busy: boolean
  onBusyChange: (busy: boolean) => void
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
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)
  const [dateRange, setDateRange] = useState<DateRange>('7d')
  const [settings, setSettings] = useState<AnalyticsSettings>({
    analytics_enabled: false,
    show_views_on_posts: false,
  })
  const [totalViews, setTotalViews] = useState(0)
  const [totalUnique, setTotalUnique] = useState(0)
  const [topPage, setTopPage] = useState<string>('—')
  const [paths, setPaths] = useState<PathHit[]>([])
  const [selectedPath, setSelectedPath] = useState<{ path: string; path_id: number } | null>(null)
  const [referrers, setReferrers] = useState<ReferrerEntry[]>([])
  const [referrersLoading, setReferrersLoading] = useState(false)
  const [browsers, setBrowsers] = useState<BreakdownEntry[]>([])
  const [operatingSystems, setOperatingSystems] = useState<BreakdownEntry[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const localBusy = saving
  const onBusyChangeRef = useRef(onBusyChange)
  onBusyChangeRef.current = onBusyChange

  useEffect(() => {
    onBusyChangeRef.current(localBusy)
  }, [localBusy])

  const initialLoadRef = useRef(false)
  useEffect(() => {
    if (!initialLoadRef.current) {
      initialLoadRef.current = true
      void loadDashboard(dateRange)
    }
  })

  async function loadDashboard(range: DateRange) {
    setLoading(true)
    setUnavailable(false)
    const { start, end } = getDateRange(range)
    try {
      const [settingsData, statsData, pathsData, browsersData, osData] = await Promise.all([
        fetchAnalyticsSettings(),
        fetchTotalStats(start, end),
        fetchPathHits(start, end),
        fetchBreakdown('browsers', start, end),
        fetchBreakdown('systems', start, end),
      ])
      setSettings(settingsData)
      setTotalViews(statsData.total_views)
      setTotalUnique(statsData.total_unique)
      setPaths(pathsData.paths)
      setBrowsers(browsersData.entries)
      setOperatingSystems(osData.entries)
      // Top page: the path with the most views
      if (pathsData.paths.length > 0) {
        const sorted = [...pathsData.paths].sort((a, b) => b.views - a.views)
        if (sorted[0]) setTopPage(sorted[0].path)
      } else {
        setTopPage('—')
      }
    } catch {
      setUnavailable(true)
    } finally {
      setLoading(false)
    }
  }

  async function handleRangeChange(range: DateRange) {
    setDateRange(range)
    setSelectedPath(null)
    await loadDashboard(range)
  }

  async function handleToggle(field: keyof AnalyticsSettings, value: boolean) {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateAnalyticsSettings({ ...settings, [field]: value })
      setSettings(updated)
    } catch {
      setSaveError('Failed to update setting. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  async function handlePathClick(path: PathHit, pathId: number) {
    setSelectedPath({ path: path.path, path_id: pathId })
    setReferrersLoading(true)
    try {
      const data = await fetchPathReferrers(pathId)
      setReferrers(data.referrers)
    } catch {
      setReferrers([])
    } finally {
      setReferrersLoading(false)
    }
  }

  const allBusy = busy || localBusy

  return (
    <div className="space-y-6">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Date range buttons */}
        <div className="flex items-center gap-1">
          {(['7d', '30d', '90d'] as const).map((range) => (
            <button
              key={range}
              onClick={() => void handleRangeChange(range)}
              disabled={allBusy || loading}
              aria-label={`Last ${range === '7d' ? '7 days' : range === '30d' ? '30 days' : '90 days'}`}
              className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                dateRange === range
                  ? 'bg-accent text-white'
                  : 'text-muted hover:text-ink border border-border hover:bg-surface'
              }`}
            >
              {range}
            </button>
          ))}
        </div>

        {/* Toggle switches */}
        <div className="flex flex-wrap items-center gap-6">
          <ToggleSwitch
            id="analytics-enabled"
            label="Analytics enabled"
            checked={settings.analytics_enabled}
            disabled={allBusy || loading}
            onChange={(value) => void handleToggle('analytics_enabled', value)}
          />
          <ToggleSwitch
            id="show-views-on-posts"
            label="Show views on posts"
            checked={settings.show_views_on_posts}
            disabled={allBusy || loading}
            onChange={(value) => void handleToggle('show_views_on_posts', value)}
          />
        </div>
      </div>

      {saveError !== null && (
        <p className="text-sm text-red-600 dark:text-red-400">{saveError}</p>
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
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Total Views</p>
              <p className="text-2xl font-semibold text-ink">{totalViews.toLocaleString()}</p>
            </div>
            <div className="bg-surface border border-border rounded-lg px-5 py-4">
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Unique Visitors</p>
              <p className="text-2xl font-semibold text-ink">{totalUnique.toLocaleString()}</p>
            </div>
            <div className="bg-surface border border-border rounded-lg px-5 py-4">
              <p className="text-xs text-muted uppercase tracking-wide mb-1">Top Page</p>
              <p className="text-sm font-medium text-ink truncate" title={topPage}>
                {topPage}
              </p>
            </div>
          </div>

          {/* Top pages table */}
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-sm font-medium text-ink mb-4">Top pages</h3>
            {paths.length === 0 ? (
              <p className="text-muted text-sm">No page data for selected range.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 pr-4 text-muted font-medium">Page path</th>
                      <th className="text-right py-2 pr-4 text-muted font-medium">Views</th>
                      <th className="text-right py-2 text-muted font-medium">Unique</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...paths].sort((a, b) => b.views - a.views).map((p) => (
                      <tr
                        key={p.path}
                        role="button"
                        tabIndex={0}
                        className="border-b border-border last:border-0 hover:bg-base cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40"
                        onClick={() => void handlePathClick(p, p.path_id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            void handlePathClick(p, p.path_id)
                          }
                        }}
                        aria-label={`View referrers for ${p.path}`}
                      >
                        <td className="py-2 pr-4 text-ink font-mono text-xs">{p.path}</td>
                        <td className="py-2 pr-4 text-right text-ink">{p.views.toLocaleString()}</td>
                        <td className="py-2 text-right text-ink">{p.unique.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Page detail drill-down */}
          {selectedPath !== null && (
            <div className="bg-surface border border-border rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-ink">
                  Referrers for{' '}
                  <span className="font-mono text-xs text-accent">{selectedPath.path}</span>
                </h3>
                <button
                  onClick={() => setSelectedPath(null)}
                  aria-label="Close referrers panel"
                  className="text-xs text-muted hover:text-ink transition-colors"
                >
                  Close
                </button>
              </div>
              {referrersLoading ? (
                <div
                  className="flex items-center justify-center py-6"
                  role="status"
                  aria-label="Loading"
                >
                  <Loader2 size={16} className="text-accent animate-spin" />
                </div>
              ) : referrers.length === 0 ? (
                <p className="text-muted text-sm">No referrer data for this page.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="text-left py-2 pr-4 text-muted font-medium">Referrer</th>
                        <th className="text-right py-2 text-muted font-medium">Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {referrers.map((r) => (
                        <tr
                          key={r.referrer}
                          className="border-b border-border last:border-0"
                        >
                          <td className="py-2 pr-4 text-ink">{r.referrer}</td>
                          <td className="py-2 text-right text-ink">{r.count.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Breakdown panels */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Browsers */}
            <div className="bg-surface border border-border rounded-lg p-5">
              <h3 className="text-sm font-medium text-ink mb-4">Browsers</h3>
              {browsers.length === 0 ? (
                <p className="text-muted text-sm">No data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart
                    data={browsers.slice(0, 8)}
                    layout="vertical"
                    margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
                  >
                    <XAxis type="number" tick={{ fontSize: 10 }} unit="%" />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fontSize: 10 }}
                      width={70}
                    />
                    <Tooltip formatter={(v) => [`${v as number}%`, 'Share']} />
                    <Bar
                      dataKey="percent"
                      fill="var(--color-accent, #6366f1)"
                      fillOpacity={0.75}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Operating Systems */}
            <div className="bg-surface border border-border rounded-lg p-5">
              <h3 className="text-sm font-medium text-ink mb-4">Operating Systems</h3>
              {operatingSystems.length === 0 ? (
                <p className="text-muted text-sm">No data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart
                    data={operatingSystems.slice(0, 8)}
                    layout="vertical"
                    margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
                  >
                    <XAxis type="number" tick={{ fontSize: 10 }} unit="%" />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fontSize: 10 }}
                      width={70}
                    />
                    <Tooltip formatter={(v) => [`${v as number}%`, 'Share']} />
                    <Bar
                      dataKey="percent"
                      fill="var(--color-accent, #6366f1)"
                      fillOpacity={0.6}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
